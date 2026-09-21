import asyncio
import io
import logging
from datetime import timedelta
from uuid import uuid4

import pytest
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError
from temporalio.worker import Replayer, Worker
from test_project_codex_execution import temporal_env as temporal_env

from tin_lite.activity_lanes import ActivityLaneInterceptor, trusted_task_queue, workflow_runner
from tin_lite.codex_execution import ProjectCodexExecution, execute_project_codex
from tin_lite.workflows import CodexProcedureWorkflow, ContentDraftDeliveryWorkflow


@workflow.defn(name="codex.procedure")
class BeforeDelivery:
    """Freeze the pre-delivery successful path, including a historical approval."""

    def __init__(self):
        self.approved = False

    @workflow.signal(name="approve")
    async def approve(self):
        self.approved = True

    @workflow.run
    async def run(self, run_id: str):
        if workflow.patched("codex-procedure-trusted-preparation-v1"):
            await workflow.execute_activity(
                "prepare_codex_procedure",
                run_id,
                start_to_close_timeout=timedelta(minutes=15),
                heartbeat_timeout=timedelta(seconds=20),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        if workflow.patched("project-codex-procedure-v1"):
            await execute_project_codex(run_id, "procedure")
        await workflow.execute_activity(
            "commit_codex_procedure_artifact",
            run_id,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=5),
        )
        required = await workflow.execute_activity(
            "request_codex_procedure_review",
            run_id,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=5),
        )
        if required:
            await workflow.wait_condition(lambda: self.approved)
            await workflow.execute_activity(
                "record_codex_procedure_approval",
                run_id,
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=5),
            )
        await workflow.execute_activity(
            "project_codex_procedure_result",
            run_id,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=5),
        )


@pytest.fixture
def rich_root_handler():
    """The serve process logs through the MCP server's Rich handler on the root logger."""
    # Imported here: other tests load this module's workflow classes inside the sandbox.
    from rich.console import Console
    from rich.logging import RichHandler

    handler = RichHandler(console=Console(file=io.StringIO()), rich_tracebacks=True)
    logging.getLogger().addHandler(handler)
    yield
    logging.getLogger().removeHandler(handler)


async def test_delivery_follows_approval_and_retries_without_codex(temporal_env, rich_root_handler):
    # A failed delivery is logged from workflow code. That log must not fail the workflow task.
    events = []
    review = asyncio.Event()
    fail_delivery = True
    project, run_id, queue = str(uuid4()), str(uuid4()), f"delivery-{uuid4()}"
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
    ]

    def stub(name):
        @activity.defn(name=name)
        async def execute(value):
            assert value == run_id  # No draft/configuration/file bytes enter history.
            events.append(name)
            if name == "resolve_codex_project":
                return project
            if name == "prepare_codex_procedure":
                return False
            if name == "request_codex_procedure_review":
                review.set()
                return True
            if name == "deliver_content_draft":
                assert activity.info().task_queue == trusted_task_queue(queue)
                if fail_delivery:
                    raise ApplicationError("Synthetic GitHub outage", non_retryable=True)
            return None

        return execute

    activities = [stub(n) for n in names]
    options = dict(
        task_queue=queue,
        workflows=[CodexProcedureWorkflow, ProjectCodexExecution, ContentDraftDeliveryWorkflow],
        workflow_runner=workflow_runner(),
        activities=activities,
        interceptors=[ActivityLaneInterceptor()],
    )
    async with (
        Worker(temporal_env.client, **options),
        Worker(temporal_env.client, task_queue=trusted_task_queue(queue), activities=activities),
    ):
        handle = await temporal_env.client.start_workflow(
            CodexProcedureWorkflow.run, run_id, id=f"draft-{run_id}", task_queue=queue
        )
        await asyncio.wait_for(review.wait(), 15)
        assert "deliver_content_draft" not in events
        await handle.signal("approve")
        await asyncio.wait_for(handle.result(), 15)
        assert events[-2:] == ["project_codex_procedure_result", "deliver_content_draft"]
        assert "project_codex_procedure_failure" not in events
        history = await handle.fetch_history()
    # New worker, same approved draft. This is solely a delivery retry.
    fail_delivery = False
    async with (
        Worker(temporal_env.client, **options),
        Worker(temporal_env.client, task_queue=trusted_task_queue(queue), activities=activities),
    ):
        await temporal_env.client.execute_workflow(
            ContentDraftDeliveryWorkflow.run,
            run_id,
            id=f"content-delivery:{run_id}",
            task_queue=queue,
        )
    assert events.count("persist_codex_procedure_artifact") == 1
    assert events.count("record_codex_procedure_approval") == 1
    assert events.count("deliver_content_draft") == 2
    await Replayer(
        workflows=[CodexProcedureWorkflow], interceptors=[ActivityLaneInterceptor()]
    ).replay_workflow(history)

    # Replay a real history recorded without the new patch or delivery activity.
    events.clear()
    review.clear()
    legacy_options = {**options, "workflows": [BeforeDelivery, ProjectCodexExecution]}
    async with (
        Worker(temporal_env.client, **legacy_options),
        Worker(temporal_env.client, task_queue=trusted_task_queue(queue), activities=activities),
    ):
        legacy = await temporal_env.client.start_workflow(
            BeforeDelivery.run, run_id, id=f"legacy-{run_id}", task_queue=queue
        )
        await asyncio.wait_for(review.wait(), 15)
        await legacy.signal("approve")
        await asyncio.wait_for(legacy.result(), 15)
        historical = await legacy.fetch_history()
    assert "deliver_content_draft" not in events
    await Replayer(
        workflows=[CodexProcedureWorkflow], interceptors=[ActivityLaneInterceptor()]
    ).replay_workflow(historical)
