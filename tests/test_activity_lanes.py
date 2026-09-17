"""Real local Temporal queues, with no provider, sandbox or production access."""

from __future__ import annotations

import asyncio
import shutil
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from temporalio import activity, workflow
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from tin_lite.activity_lanes import (
    ActivityLaneInterceptor,
    _LaneOutbound,
    trusted_task_queue,
)
from tin_lite.codex_execution import ProjectCodexExecution
from tin_lite.worker_group import WorkerGroup
from tin_lite.workflows import CodexProcedureWorkflow, ProjectTaskWorkflow


@workflow.defn
class SaveProbe:
    @workflow.run
    async def run(self, run_id: str) -> None:
        await workflow.execute_activity(
            "commit_codex_procedure_artifact",
            run_id,
            start_to_close_timeout=timedelta(seconds=10),
        )
        await workflow.execute_activity(
            "request_codex_procedure_review",
            run_id,
            start_to_close_timeout=timedelta(seconds=10),
        )


@pytest.mark.asyncio
async def test_codex_backlog_cannot_block_save_and_review_or_overlap_codex():
    binary = shutil.which("temporal")
    if binary is None:
        pytest.skip("local Temporal CLI is needed for queue integration")
    started, release = asyncio.Event(), asyncio.Event()
    active = peak = calls = 0
    observed = []

    def stub(name):
        @activity.defn(name=name)
        async def execute(payload):
            nonlocal active, peak, calls
            observed.append((name, activity.info().task_queue))
            if name == "resolve_codex_project":
                return str(payload)
            if name in {"run_project_task_turn", "persist_codex_procedure_artifact"}:
                active += 1
                calls += 1
                peak = max(peak, active)
                started.set()
                try:
                    await release.wait()
                finally:
                    active -= 1
                return "completed" if name == "run_project_task_turn" else None
            if name == "request_codex_procedure_review":
                return True
            if name == "prepare_codex_procedure":
                return False
            return None

        return execute

    names = [
        "resolve_codex_project",
        "run_project_task_turn",
        "prepare_codex_procedure",
        "create_codex_procedure_sandbox",
        "persist_codex_procedure_artifact",
        "commit_codex_procedure_artifact",
        "request_codex_procedure_review",
        "record_codex_procedure_approval",
        "project_codex_procedure_result",
        "deliver_content_draft",
    ]
    activities = {name: stub(name) for name in names}
    base = f"lane-test-{uuid4()}"
    async with await WorkflowEnvironment.start_local(
        dev_server_existing_path=binary,
        dev_server_log_level="error",
    ) as env:
        serial = Worker(
            env.client,
            task_queue=base,
            max_concurrent_activities=1,
            workflows=[
                SaveProbe,
                ProjectTaskWorkflow,
                CodexProcedureWorkflow,
                ProjectCodexExecution,
            ],
            activities=list(activities.values()),
            interceptors=[ActivityLaneInterceptor()],
        )
        trusted = Worker(
            env.client,
            task_queue=trusted_task_queue(base),
            max_concurrent_activities=4,
            activities=[
                activities[n]
                for n in names
                if n
                not in {
                    "run_project_task_turn",
                    "create_codex_procedure_sandbox",
                    "persist_codex_procedure_artifact",
                }
            ],
        )
        async with serial, trusted:
            handles = []
            try:
                for _ in range(8):
                    handles.append(
                        await env.client.start_workflow(
                            ProjectTaskWorkflow.run,
                            str(uuid4()),
                            id=str(uuid4()),
                            task_queue=base,
                        )
                    )
                await asyncio.wait_for(started.wait(), 15)
                probe = await env.client.start_workflow(
                    SaveProbe.run,
                    str(uuid4()),
                    id=str(uuid4()),
                    task_queue=base,
                )
                # More queued compute than all available activity slots; no semaphore starvation.
                await asyncio.wait_for(probe.result(), 10)
                assert active == peak == calls == 1
                assert observed[-2:] == [
                    ("commit_codex_procedure_artifact", trusted_task_queue(base)),
                    ("request_codex_procedure_review", trusted_task_queue(base)),
                ]
                history = await probe.fetch_history()
            finally:
                release.set()
            await asyncio.wait_for(asyncio.gather(*(h.result() for h in handles)), 20)
            assert peak == 1 and calls == 8
            # A real procedure still reaches its normal review gate, then finalizes once approved.
            procedure = await env.client.start_workflow(
                CodexProcedureWorkflow.run,
                str(uuid4()),
                id=str(uuid4()),
                task_queue=base,
            )
            await procedure.signal("approve")
            await asyncio.wait_for(procedure.result(), 15)
            assert peak == 1 and calls == 9
            procedure_history = await procedure.fetch_history()
        for recorded in (history, procedure_history):
            await Replayer(
                workflows=[SaveProbe, CodexProcedureWorkflow],
                interceptors=[ActivityLaneInterceptor()],
            ).replay_workflow(recorded)


@pytest.mark.asyncio
async def test_already_scheduled_legacy_activity_drains_without_rerouting():
    binary = shutil.which("temporal")
    if binary is None:
        pytest.skip("local Temporal CLI is needed for queue integration")
    seen = []

    def stub(name):
        @activity.defn(name=name)
        async def execute(run_id: str):
            seen.append(activity.info().task_queue)
            return True

        return execute

    base = f"legacy-lane-test-{uuid4()}"
    async with await WorkflowEnvironment.start_local(
        dev_server_existing_path=binary,
        dev_server_log_level="error",
    ) as env:
        # Old worker schedules save on the original queue but has no activity poller.
        async with Worker(env.client, task_queue=base, workflows=[SaveProbe]):
            handle = await env.client.start_workflow(
                SaveProbe.run,
                str(uuid4()),
                id=str(uuid4()),
                task_queue=base,
            )
            async with asyncio.timeout(15):
                # Poll external server state; there is no local activity/event to await yet.
                while not (await handle.describe()).raw_description.pending_activities:  # noqa: ASYNC110
                    await asyncio.sleep(0.05)
        async with (
            Worker(
                env.client,
                task_queue=base,
                workflows=[SaveProbe],
                activities=[stub("commit_codex_procedure_artifact")],
                interceptors=[ActivityLaneInterceptor()],
                max_concurrent_activities=1,
            ),
            Worker(
                env.client,
                task_queue=trusted_task_queue(base),
                activities=[stub("request_codex_procedure_review")],
            ),
        ):
            await asyncio.wait_for(handle.result(), 15)
            history = await handle.fetch_history()
        assert seen == [base, trusted_task_queue(base)]
        await Replayer(
            workflows=[SaveProbe],
            interceptors=[ActivityLaneInterceptor()],
        ).replay_workflow(history)


def test_unknown_or_explicit_other_queue_does_not_get_trusted_routing(monkeypatch):
    monkeypatch.setattr(workflow, "info", lambda: SimpleNamespace(task_queue="base"))
    next = MagicMock()
    outbound = _LaneOutbound(next)
    for name, queue in [
        ("new_codex_activity", None),
        ("run_project_task_turn", None),
        ("project_codex_procedure_result", "explicit-other"),
    ]:
        input = SimpleNamespace(activity=name, task_queue=queue, disable_eager_execution=False)
        outbound.start_activity(input)
        assert input.task_queue == queue


@pytest.mark.asyncio
async def test_worker_failure_stops_sibling_before_group_returns():
    stopped = asyncio.Event()

    class FakeWorker:
        def __init__(self, fail=False):
            self.fail = fail

        async def run(self):
            if self.fail:
                raise RuntimeError("worker failed")
            await stopped.wait()

        async def shutdown(self):
            stopped.set()

    with pytest.raises(RuntimeError, match="worker failed"):
        await asyncio.wait_for(WorkerGroup(FakeWorker(), FakeWorker(True)).run(), 5)
    assert stopped.is_set()
