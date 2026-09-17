"""Real Temporal: upgrade a waiting history, revisions, failed child and composing parent."""

import asyncio
from uuid import uuid4

import pytest
from temporalio import activity, workflow
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.worker import Replayer, Worker
from test_content_delivery_temporal import BeforeDelivery
from test_project_codex_execution import temporal_env as temporal_env

from tin_lite.activity_lanes import ActivityLaneInterceptor, trusted_task_queue
from tin_lite.codex_execution import ProjectCodexExecution
from tin_lite.workflows import CodexProcedureWorkflow


@workflow.defn
class ReviewParent:
    @workflow.run
    async def run(self, root: str) -> str:
        return await workflow.execute_child_workflow(
            "codex.procedure", root, id=f"codex.procedure:{root}"
        )


@pytest.mark.parametrize("final_action", ["approve", "cancel", "stop_before_dispatch"])
async def test_waiting_history_upgrade_revision_chain_failure_retry_and_parent(
    temporal_env, final_action
):
    queue = f"review-{uuid4()}"
    root, second, failed, final = [str(uuid4()) for _ in range(4)]
    commands = {str(uuid4()): second, str(uuid4()): failed, str(uuid4()): final}
    events, ready, failures = [], {}, asyncio.Event()
    names = [
        "prepare_codex_procedure",
        "resolve_codex_project",
        "create_codex_procedure_sandbox",
        "persist_codex_procedure_artifact",
        "commit_codex_procedure_artifact",
        "request_codex_procedure_review",
        "record_codex_procedure_approval",
        "project_codex_procedure_result",
        "project_codex_procedure_failure",
        "deliver_content_draft",
        "receive_workflow_revision",
    ]

    def stub(name):
        @activity.defn(name=name)
        async def execute(value):
            run_id = value["run_id"] if isinstance(value, dict) else value
            events.append((name, run_id))
            if name == "resolve_codex_project":
                return "one-project"
            if name == "prepare_codex_procedure":
                if run_id == failed:
                    raise ApplicationError("Synthetic generation failure", non_retryable=True)
                return False
            if name == "project_codex_procedure_failure":
                failures.set()
            if name == "request_codex_procedure_review":
                ready.setdefault(run_id, asyncio.Event()).set()
                return True
            if name == "receive_workflow_revision":
                successor = commands[value["command_id"]]
                return {
                    "run_id": successor,
                    "temporal_workflow_id": f"codex.procedure:{successor}",
                    "stopped": successor == final and final_action == "stop_before_dispatch",
                }
            return None

        return execute

    activities = [stub(name) for name in names]

    async def wait_ready(run_id):
        await asyncio.wait_for(ready.setdefault(run_id, asyncio.Event()).wait(), 20)

    async with (
        Worker(
            temporal_env.client,
            task_queue=queue,
            workflows=[BeforeDelivery, ReviewParent, ProjectCodexExecution],
            activities=activities,
            interceptors=[ActivityLaneInterceptor()],
        ),
        Worker(temporal_env.client, task_queue=trusted_task_queue(queue), activities=activities),
    ):
        parent = await temporal_env.client.start_workflow(
            ReviewParent.run,
            root,
            id=f"parent:{root}",
            task_queue=queue,
        )
        await wait_ready(root)
    # No old worker or sandbox session survives. The existing history continues.
    handle = temporal_env.client.get_workflow_handle(f"codex.procedure:{root}")
    async with (
        Worker(
            temporal_env.client,
            task_queue=queue,
            workflows=[CodexProcedureWorkflow, ReviewParent, ProjectCodexExecution],
            activities=activities,
            interceptors=[ActivityLaneInterceptor()],
        ),
        Worker(temporal_env.client, task_queue=trusted_task_queue(queue), activities=activities),
    ):
        ids = list(commands)
        await handle.signal("request_revision", ids[0])
        await handle.signal("request_revision", ids[0])  # Lost acknowledgement/reconciliation.
        await wait_ready(second)
        second_handle = temporal_env.client.get_workflow_handle(f"codex.procedure:{second}")
        await second_handle.signal("request_revision", ids[1])
        await asyncio.wait_for(failures.wait(), 20)
        assert not any(name == "deliver_content_draft" for name, _ in events)
        # The nearest waiting ancestor coordinates the explicit retry of its failed child.
        await second_handle.signal("request_revision", ids[2])
        if final_action != "stop_before_dispatch":
            await wait_ready(final)
            final_handle = temporal_env.client.get_workflow_handle(f"codex.procedure:{final}")
            if final_action == "approve":
                await final_handle.signal("approve")
            else:
                await final_handle.cancel()
        if final_action == "approve":
            assert await asyncio.wait_for(parent.result(), 20) == final
        else:
            with pytest.raises(WorkflowFailureError):
                await asyncio.wait_for(parent.result(), 20)
        history = await handle.fetch_history()
    approved = [final] if final_action == "approve" else []
    assert [run for name, run in events if name == "deliver_content_draft"] == approved
    assert [run for name, run in events if name == "record_codex_procedure_approval"] == approved
    assert events.count(("receive_workflow_revision", root)) == 1
    await Replayer(
        workflows=[CodexProcedureWorkflow], interceptors=[ActivityLaneInterceptor()]
    ).replay_workflow(history)
