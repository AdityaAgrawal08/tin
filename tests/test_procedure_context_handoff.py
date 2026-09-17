"""The procedure context reaches the sandbox as a file; the variable only while it fits."""

from __future__ import annotations

import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_codex_isolation import base_values

from tin_lite.e2b_runtime import CONTEXT_ENV_MAX, CONTEXT_PATH, E2BRuntime, SandboxProcedureInput


@pytest.mark.parametrize("large", [False, True])
@pytest.mark.parametrize("companion", [False, True])
async def test_context_is_written_to_a_file_and_the_variable_only_when_small(
    monkeypatch, large, companion
):
    written: dict[str, bytes] = {}
    seen: dict[str, dict] = {}
    payload = base64.b64encode(json.dumps({"summary": "done", "message": "ok"}).encode()).decode()
    output = f"TIN_PROCEDURE_COMMIT_SHA={'c' * 40}\nTIN_PROCEDURE_RESULT={payload}\n"

    async def write(path, data):
        written[path] = data if isinstance(data, bytes) else data.encode()

    async def command(cmd, **kwargs):
        if cmd.endswith("isolated-procedure check"):
            return SimpleNamespace(stdout="TIN_ISOLATION_READY_V1")
        if cmd.endswith("--check-companion"):
            seen["preflight"] = True
            return SimpleNamespace(stdout="TIN_PROCEDURE_COMPANION_V1\n")
        if cmd.endswith("codex_api_config.py --check"):
            return SimpleNamespace(stdout="TIN_CODEX_API_READY_V1")
        assert cmd == "/opt/tin-lite/run-procedure"
        seen["envs"] = kwargs["envs"]
        return SimpleNamespace(wait=AsyncMock(return_value=SimpleNamespace(stdout=output)))

    sandbox = SimpleNamespace(
        commands=SimpleNamespace(run=command),
        files=SimpleNamespace(write=write),
        kill=AsyncMock(),
    )
    monkeypatch.setattr(
        "tin_lite.e2b_runtime.AsyncSandbox.connect", AsyncMock(return_value=sandbox)
    )
    runtime = E2BRuntime(
        api_key="synthetic",
        template="default",
        timeout_seconds=900,
        egress_allow_hosts=("proxy.test",),
    )
    context = {"prompt": "x" * (CONTEXT_ENV_MAX if large else 10), "inputs": {"a": 1}}
    if companion:
        context["output"] = {"companion_path": "report.generation.md"}
    run_input = SandboxProcedureInput(
        **base_values(),
        context=context,
        output_path="report.md",
        output_max_bytes=1000,
        isolated=True,
        usage_sink=AsyncMock(),
        api_url="https://tin.test/relay",
        api_grant="synthetic-relay-grant",
    )
    result = await runtime.run_procedure_and_kill(sandbox_id="sandbox", run_input=run_input)
    assert result.summary == "done"
    assert json.loads(written[CONTEXT_PATH]) == context
    envs = seen["envs"]
    assert envs["TIN_PROCEDURE_CONTEXT_PATH"] == CONTEXT_PATH
    assert seen.get("preflight", False) == companion
    assert envs.get("TIN_PROCEDURE_COMPANION_PATH") == (
        "report.generation.md" if companion else None
    )
    if large:
        assert "TIN_PROCEDURE_CONTEXT_B64" not in envs
    else:
        assert json.loads(base64.b64decode(envs["TIN_PROCEDURE_CONTEXT_B64"])) == context


@pytest.mark.parametrize("editorial", [False, True])
async def test_old_image_rejected_before_runner_or_context_transfer(monkeypatch, editorial):
    sandbox = SimpleNamespace(
        commands=SimpleNamespace(run=AsyncMock(return_value=SimpleNamespace(stdout="old image"))),
        files=SimpleNamespace(write=AsyncMock()),
        kill=AsyncMock(),
    )
    monkeypatch.setattr(
        "tin_lite.e2b_runtime.AsyncSandbox.connect", AsyncMock(return_value=sandbox)
    )
    runtime = E2BRuntime(
        api_key="synthetic",
        template="default",
        timeout_seconds=900,
        egress_allow_hosts=("proxy.test",),
    )
    value = SandboxProcedureInput(
        **base_values(),
        context={
            "output": {
                "companion_path": "report.generation.md",
                **({"validator": "content-draft.v3"} if editorial else {}),
            }
        },
        output_path="report.md",
        output_max_bytes=1000,
        isolated=True,
        usage_sink=AsyncMock(),
        api_url="https://tin.test/relay",
        api_grant="synthetic-relay-grant",
    )
    with pytest.raises(
        RuntimeError,
        match=("editorial assessment support" if editorial else "companion document support"),
    ):
        await runtime.run_procedure_and_kill(sandbox_id="sandbox", run_input=value)
    assert sandbox.commands.run.await_count == 1
    sandbox.files.write.assert_not_called()
    sandbox.kill.assert_awaited_once()
