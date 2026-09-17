"""Opt-in real calendar/MCP/E2B/storage proof; local DB and fixture OAuth verification."""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from dotenv import dotenv_values
from temporalio.worker import Replayer, Worker
from test_billing import billed as billed
from test_code_models import http_mcp
from test_private_workflows import structured
from test_procedure_publication import publication_db as publication_db
from test_project_codex_execution import temporal_env as temporal_env
from test_workflow_code import OUTPUT, PATH, activate_code, setup

from tin_lite.code_storage import CodeStorage
from tin_lite.codex_execution import ProjectCodexExecution
from tin_lite.e2b_runtime import E2BRuntime
from tin_lite.schedules import TemporalScheduleService
from tin_lite.workflow_code import example_files
from tin_lite.workflows import CodeWorkflow, ScheduledDispatchWorkflow


@pytest.mark.skipif(
    os.environ.get("TIN_LITE_CODE_SCHEDULE_LIVE_PROOF") != "1", reason="real E2B/storage opt-in"
)
async def test_calendar_runs_with_author_offline_at_zero_credits(
    billed, temporal_env, monkeypatch, tmp_path
):
    f = billed
    env = dotenv_values(".env")
    storage = CodeStorage(
        organization=env.get("TIN_LITE_CODE_STORAGE_ORG") or "tin",
        private_key=env["CODE_STORAGE_API_KEY"],
    )
    repo_id = f"projects/{f.project.id}"
    repo = await storage.ensure_repo(repo_id)
    await f.db.pool.execute(
        "UPDATE projects SET state_repo_id=$2 WHERE id=$1", f.project.id, repo_id
    )
    f.project = await f.db.get_project(f.project.id)
    compute = E2BRuntime(
        api_key=env["E2B_API_KEY"],
        template="tin-lite-codex",
        isolated_template=env.get("TIN_LITE_E2B_ISOLATED_TEMPLATE") or "tin-lite-codex-isolated",
        timeout_seconds=60,
        egress_allow_hosts=(),
        usage_database=f.db,
    )
    _, common, code = await setup(
        f, monkeypatch, temporal=temporal_env.client, compute=compute, storage=storage
    )
    common._temporal = temporal_env.client
    common._integrations = f.runtime.integrations
    assert not getattr(f.settings, "luna_api_key", None)
    files = example_files()
    manifest = json.loads(files[PATH])
    manifest["definition"]["schedule_modes"] = ["on_demand", "daily", "weekly"]
    files[PATH] = json.dumps(manifest)
    async with http_mcp(f, monkeypatch) as wire:
        committed = structured(
            await wire.call_tool(
                "commit_project_changes",
                {
                    "project_id": str(f.project.id),
                    "expected_revision": await storage.head_sha(repo, "main"),
                    "request_id": str(uuid4()),
                    "message": "Author scheduled fixture report locally",
                    "changes": [
                        {"operation": "upsert", "path": p, "content": raw}
                        for p, raw in files.items()
                    ],
                },
            )
        )
        active = await activate_code(f, wire, revision=committed["revision"])
        due = (datetime.now(UTC) + timedelta(minutes=1)).replace(second=0, microsecond=0)
        if (due - datetime.now(UTC)).total_seconds() < 20:
            due += timedelta(minutes=1)
        configured = structured(
            await wire.call_tool(
                "create_project_workflow",
                {
                    "project_id": str(f.project.id),
                    "workflow_id": active["workflow_id"],
                    "name": "Scheduled report with author offline",
                    "inputs": {"minimum_cents": 1000},
                    "request_id": str(uuid4()),
                    "schedule": {
                        "cadence": "daily",
                        "local_time": due.strftime("%H:%M"),
                        "timezone": "UTC",
                        "end_at": (due + timedelta(minutes=1)).isoformat(),
                    },
                },
            )
        )
    # The authoring MCP client is closed before the calendar fires. No manual trigger.
    implementations = [ScheduledDispatchWorkflow, CodeWorkflow, ProjectCodexExecution]
    try:
        async with Worker(
            temporal_env.client,
            task_queue=f.settings.task_queue,
            workflows=implementations,
            activities=[
                common.dispatch_scheduled_workflow,
                common.resolve_codex_project,
                code.execute,
                code.publish,
                code.review,
                code.approve,
                code.project,
                code.failure,
            ],
        ):
            async with asyncio.timeout(180):
                while True:
                    row = await f.db.pool.fetchrow(
                        "SELECT * FROM workflow_runs WHERE project_workflow_id=$1",
                        UUID(configured["id"]),
                    )
                    if row and row["status"] in {"succeeded", "failed", "stopped"}:
                        break
                    await asyncio.sleep(1)
            assert row["status"] == "succeeded", row["error_message"]
            run = await f.db.get_run(row["id"])
            handle = temporal_env.client.get_workflow_handle(run.temporal_workflow_id)
            await asyncio.wait_for(handle.result(), 30)
            history = await handle.fetch_history()
            await Replayer(workflows=implementations).replay_workflow(history)
            # Repeating the same inputs must succeed even when the report has no diff.
            async with http_mcp(f, monkeypatch) as wire:
                repeated = structured(
                    await wire.call_tool(
                        "start_project_workflow",
                        {
                            "project_id": str(f.project.id),
                            "project_workflow_id": configured["id"],
                            "request_id": str(uuid4()),
                        },
                    )
                )
            repeat = await f.db.get_run(UUID(repeated["id"]))
            await asyncio.wait_for(
                temporal_env.client.get_workflow_handle(repeat.temporal_workflow_id).result(), 120
            )
            repeat = await f.db.get_run(repeat.id)
            assert repeat.status.value == "succeeded"
            assert repeat.canonical_commit_sha == run.canonical_commit_sha
            assert not await compute.is_running(repeat.sandbox_id)
        assert not await compute.is_running(run.sandbox_id)
        async with http_mcp(f, monkeypatch) as wire:
            output = structured(await wire.call_tool("read_run_output", {"run_id": str(run.id)}))
        assert "3900 cents" in output["content"]
        assert (
            await storage.read_canonical_artifact(
                repo_id=repo_id, commit_sha=run.canonical_commit_sha, path=OUTPUT
            )
            == output["content"].encode()
        )
        assert await f.db.pool.fetchval("SELECT count(*) FROM workflow_runs") == 2
        assert await f.db.pool.fetchval("SELECT count(*) FROM billing_operations") == 0
        assert await f.db.pool.fetchval("SELECT balance_nanos FROM billing_accounts") == 0
        proof = {
            "run_id": str(run.id),
            "scheduled_for": run.scheduled_for.isoformat(),
            "trigger_source": run.trigger_source,
            "author_offline": True,
            "sandbox_deleted": True,
            "artifact_revision": run.canonical_commit_sha,
            "unchanged_repeat_run_id": str(repeat.id),
            "repo_id": repo_id,
            "model_calls": 0,
            "credit_deductions": 0,
        }
        (tmp_path / "slice-d-live-proof.json").write_text(json.dumps(proof, indent=2))
        print(json.dumps(proof))
    finally:
        await TemporalScheduleService(client=temporal_env.client, settings=f.settings).delete(
            configured["id"]
        )
