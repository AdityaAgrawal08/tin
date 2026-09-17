"""The retired login cannot be fetched or used for new sandbox execution."""

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from test_procedure_publication import publication_db as publication_db
from test_rollouts import base_values

from tin_lite.api import router
from tin_lite.codex_api import CONTRACT, execution_profile
from tin_lite.e2b_runtime import (
    E2BRuntime,
    SandboxProcedureInput,
    SandboxRunInput,
    SandboxTaskInput,
)
from tin_lite.procedures import SandboxProfile


@pytest.mark.parametrize("profile", ["default", "browser", "studio", "isolated"])
def test_old_oauth_pin_is_refused_without_rewriting_it(profile):
    original = SandboxProfile(
        profile=profile, egress="open" if profile in {"browser", "studio"} else "fenced"
    )
    oauth = {"mode": "chatgpt_oauth"}
    with pytest.raises(ValueError, match="retired"):
        execution_profile(original, oauth)
    assert oauth == {"mode": "chatgpt_oauth"}
    assert execution_profile(original, CONTRACT).isolated


@pytest.mark.parametrize("method", ["GET", "PUT"])
async def test_removed_broker_endpoint_never_serves_or_accepts_auth(method):
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(
            method,
            "/internal/broker/auth",
            headers={"Authorization": "Bearer synthetic", "X-Tin-Sandbox-ID": "old-sandbox"},
            content=b"{}",
        )
    assert response.status_code == 404


@pytest.mark.parametrize("kind", ["design", "task", "procedure", "browser", "studio"])
async def test_unsafe_runtime_entrypoints_kill_before_connect_or_proxy(monkeypatch, kind):
    connect = AsyncMock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr("tin_lite.e2b_runtime.AsyncSandbox.connect", connect)
    runtime = E2BRuntime(
        api_key="synthetic", template="default", timeout_seconds=900, egress_allow_hosts=()
    )
    runtime.kill = AsyncMock()
    if kind == "design":
        method, value = runtime.run_and_kill, SandboxRunInput(**base_values())
    elif kind == "task":
        method, value = (
            runtime.run_task_and_kill,
            SandboxTaskInput(**base_values(), run_id="run", context={}),
        )
    else:
        method, value = (
            runtime.run_procedure_and_kill,
            SandboxProcedureInput(
                **base_values(),
                context={},
                output_path="report.md",
                output_max_bytes=100,
                isolated=kind != "procedure",
                browser=kind == "browser",
                studio=kind == "studio",
            ),
        )
    with pytest.raises(ValueError, match="disabled|protected"):
        await method(sandbox_id="sandbox", run_input=value)
    runtime.kill.assert_awaited_once_with("sandbox")
    connect.assert_not_awaited()


@pytest.mark.parametrize("name", ["design", "task", "procedure"])
def test_legacy_shell_entrypoints_fail_before_fetching_credentials(name):
    script = Path(__file__).parents[1] / "sandbox" / f"run_{name}.sh"
    result = subprocess.run(  # noqa: S603 -- repository script, empty synthetic environment
        ["/bin/bash", str(script)], env={"PATH": "/usr/bin:/bin"}, capture_output=True, check=False
    )
    assert result.returncode == 64
    assert b"legacy" in result.stderr or b"require" in result.stderr


async def test_isolated_procedure_cannot_start_without_api_route(publication_db):
    from test_private_workflows import ACTOR, KEY, activate, fixture

    from tin_lite.run_service import WorkflowExecutorUnavailableError, start_workflow_run

    f = await fixture(publication_db)
    await activate(f)
    workflow = next(w for w in await f.db.list_workflows(project_id=f.project.id) if w.key == KEY)
    f.settings.codex_api_projects = set()
    with pytest.raises(WorkflowExecutorUnavailableError, match="protected"):
        await start_workflow_run(
            runtime=f.runtime,
            settings=f.settings,
            workflow=workflow,
            project_id=f.project.id,
            started_by_clerk_user_id=ACTOR,
            input_payload={"brief": "No model request should start"},
        )
    assert await f.db.pool.fetchval("SELECT count(*) FROM workflow_runs") == 0
    f.runtime.temporal.start_workflow.assert_not_awaited()
