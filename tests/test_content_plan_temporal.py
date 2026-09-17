"""Local Temporal retry/replay proof, with no model/provider access."""

import shutil
from uuid import uuid4

import pytest
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from tin_lite.workflows import ContentPlanWorkflow


@pytest.mark.asyncio
async def test_content_plan_identifier_only_history_and_retry():
    binary = shutil.which("temporal")
    if binary is None:
        pytest.skip("Local Temporal CLI required")
    run_id, calls = str(uuid4()), []

    @activity.defn(name="content_plan_execute")
    async def execute(value: str):
        calls.append(value)
        if len(calls) == 1:
            raise ApplicationError("Synthetic transient publication error")

    @activity.defn(name="content_plan_failure")
    async def fail(value: str):
        raise AssertionError("This workflow should recover")

    async with await WorkflowEnvironment.start_local(
        dev_server_existing_path=binary, dev_server_log_level="error"
    ) as env:
        async with Worker(
            env.client,
            task_queue="content-plan-proof",
            workflows=[ContentPlanWorkflow],
            activities=[execute, fail],
        ):
            handle = await env.client.start_workflow(
                ContentPlanWorkflow.run,
                run_id,
                id=f"content-plan-proof:{run_id}",
                task_queue="content-plan-proof",
            )
            await handle.result()
            history = await handle.fetch_history()
        await Replayer(workflows=[ContentPlanWorkflow]).replay_workflow(history)
    assert calls == [run_id, run_id]
    for event in history.events:
        if event.HasField("activity_task_scheduled_event_attributes"):
            payloads = event.activity_task_scheduled_event_attributes.input.payloads
            assert len(payloads) == 1 and payloads[0].data == f'"{run_id}"'.encode()
