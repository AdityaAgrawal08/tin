"""Opt-in real isolated execution; provider data/model and OAuth identity are fixtures."""

import asyncio
import json
import os
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr
from temporalio.worker import Replayer, Worker
from test_billing import billed as billed
from test_billing import fund
from test_code_models import http_mcp, sdk_router
from test_private_workflows import structured
from test_procedure_publication import publication_db as publication_db
from test_project_codex_execution import temporal_env as temporal_env
from test_project_connections import KEY, PATH, SECRET, integrations, public_dns
from test_workflow_code import setup, start

from tin_lite.code_activities import CodeActivities
from tin_lite.codex_execution import ProjectCodexExecution
from tin_lite.workflow_code import example_files
from tin_lite.workflows import CodeWorkflow


@pytest.mark.skipif(
    os.environ.get("TIN_LITE_CONNECTION_LIVE_PROOF") != "1", reason="opt-in E2B/storage"
)
async def test_real_isolated_mcp_service_model_report_and_worker_recovery(
    billed, monkeypatch, temporal_env, tmp_path
):
    import test_code_models
    from dotenv import dotenv_values

    from tin_lite.code_storage import CodeStorage
    from tin_lite.e2b_runtime import E2BRuntime

    f = billed
    env = dotenv_values(".env")
    await fund(f)
    integration_service = await integrations(f)
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

    class InterruptedCompute(E2BRuntime):
        saved = asyncio.Event()
        callbacks = 0
        sandbox_ids = []

        async def run_code_and_kill(self, *, model_call, **kwargs):
            self.sandbox_ids.append(kwargs["sandbox_id"])

            async def interrupt(payload):
                result = await model_call(payload)
                self.callbacks += 1
                if self.callbacks == 1:
                    self.saved.set()
                    raise RuntimeError("fixture worker loss after saving API result")
                return result

            return await super().run_code_and_kill(model_call=interrupt, **kwargs)

    compute = InterruptedCompute(
        api_key=env["E2B_API_KEY"],
        template="tin-lite-codex",
        isolated_template=env.get("TIN_LITE_E2B_ISOLATED_TEMPLATE") or "tin-lite-codex-isolated",
        timeout_seconds=60,
        egress_allow_hosts=(),
        usage_database=f.db,
    )
    _, common, _ = await setup(
        f, monkeypatch, temporal=temporal_env.client, compute=compute, storage=storage
    )
    common._integrations = integration_service
    monkeypatch.setattr(
        test_code_models,
        "CLASSIFIED",
        {
            "accounts": [
                {"id": "company-2", "segment": "small"},
                {"id": "company-3", "segment": "midmarket"},
            ]
        },
    )
    model_router, model_calls = sdk_router(f)
    f.settings.luna_api_key = SecretStr("test-model-configuration")
    f.runtime.model_router = model_router
    api_calls = []

    def wire(request):
        api_calls.append(request)
        assert request.headers["authorization"] == f"Bearer {SECRET}"
        return httpx.Response(
            200,
            stream=httpx.ByteStream(
                json.dumps(
                    {
                        "accounts": [
                            {"id": "company-1", "employees": 5},
                            {"id": "company-2", "employees": 30},
                            {"id": "company-3", "employees": 120},
                        ]
                    }
                ).encode()
            ),
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(wire))

    def activities():
        code = CodeActivities(common=common, model_router=model_router)
        code.services.client, code.services.resolver = client, public_dns
        return code

    def worker(code):
        return Worker(
            temporal_env.client,
            task_queue=f.settings.task_queue,
            workflows=[CodeWorkflow, ProjectCodexExecution],
            activities=[
                common.resolve_codex_project,
                code.execute,
                code.publish,
                code.review,
                code.approve,
                code.project,
                code.failure,
            ],
            graceful_shutdown_timeout=timedelta(seconds=1),
        )

    try:
        async with http_mcp(f, monkeypatch) as mcp:
            files = example_files(KEY, connections=True)
            main = f"workflow_packages/{KEY}/main.py"
            files[main] = files[main].replace(
                "async def run(ctx, inputs):",
                """async def run(ctx, inputs):
    import os, socket
    from pathlib import Path
    keys = ('CRM_KEY', 'TIN_LITE_LUNA_API_KEY', 'E2B_API_KEY', 'CODE_STORAGE_API_KEY')
    assert not any(name in os.environ for name in keys)
    with socket.socket() as direct:
        direct.settimeout(1)
        assert direct.connect_ex(('1.1.1.1', 443)) != 0
    try:
        Path('/root/tin-code/packet.json').read_bytes()
    except PermissionError:
        pass
    else:
        raise AssertionError('controller readable')
""",
            )
            committed = structured(
                await mcp.call_tool(
                    "commit_project_changes",
                    {
                        "project_id": str(f.project.id),
                        "expected_revision": await storage.head_sha(repo, "main"),
                        "request_id": str(uuid4()),
                        "message": "Slice C isolated connection proof",
                        "changes": [
                            {"operation": "upsert", "path": p, "content": raw}
                            for p, raw in files.items()
                        ],
                    },
                )
            )
            selection = {
                "project_id": str(f.project.id),
                "path": PATH,
                "revision": committed["revision"],
            }
            assert structured(await mcp.call_tool("validate_workflow_package", selection))["valid"]
            active = structured(
                await mcp.call_tool(
                    "activate_workflow_package",
                    {**selection, "expected_revision": None, "request_id": str(uuid4())},
                )
            )
            async with worker(activities()):
                run_id = (await start(f, mcp, active, inputs={"minimum_employees": 20}))["id"]
                await asyncio.wait_for(compute.saved.wait(), 100)
            async with worker(activities()):
                run = await f.db.get_run(UUID(run_id))
                handle = temporal_env.client.get_workflow_handle(run.temporal_workflow_id)
                await asyncio.wait_for(handle.result(), 180)
                history = await handle.fetch_history()
                await Replayer(workflows=[CodeWorkflow, ProjectCodexExecution]).replay_workflow(
                    history
                )
            run = await f.db.get_run(UUID(run_id))
            assert run.status.value == "succeeded"
            assert len(api_calls) == len(model_calls) == 1
            assert len(set(compute.sandbox_ids)) == 2
            for sandbox_id in compute.sandbox_ids:
                assert not await compute.is_running(sandbox_id)
            output = structured(await mcp.call_tool("read_run_output", {"run_id": run_id}))
            assert "company-2 | 30 | small" in output["content"]
            assert "company-3 | 120 | midmarket" in output["content"]
            assert (
                await storage.read_canonical_artifact(
                    repo_id=repo_id,
                    commit_sha=run.canonical_commit_sha,
                    path="reports/custom/CONNECTED_ACCOUNTS.md",
                )
                == output["content"].encode()
            )
            proof = {
                "run_id": run_id,
                "sandbox_ids": compute.sandbox_ids,
                "sandbox_deleted": True,
                "artifact_revision": run.canonical_commit_sha,
                "repo_id": repo_id,
                "api_requests": len(api_calls),
                "model_requests": len(model_calls),
                "providers": "HTTP fixtures",
                "execution": "real E2B/storage/local Temporal/HTTP MCP with test OAuth",
                "replay": "passed",
            }
            (tmp_path / "slice-c-proof.json").write_text(json.dumps(proof, indent=2))
            print(json.dumps(proof, indent=2))
    finally:
        for sandbox_id in compute.sandbox_ids:
            await compute.kill(sandbox_id)
        await client.aclose()
        await model_router.close()
        await integration_service.close()
