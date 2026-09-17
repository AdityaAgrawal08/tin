from __future__ import annotations

import asyncio
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from e2b import NotFoundException, SandboxNotFoundException
from fastapi import FastAPI

from tin_lite.api import router
from tin_lite.e2b_runtime import E2BRuntime, SandboxProcedureInput, SandboxRunInput


def sandbox_input() -> SandboxRunInput:
    return SandboxRunInput(
        execution_key="run-1:artifact_persist",
        canonical_url="https://storage.test/canonical",
        canonical_auth_header="Authorization: Basic canonical",
        canonical_branch="main",
        ephemeral_url="https://storage.test/ephemeral",
        ephemeral_auth_header="Authorization: Basic ephemeral",
        ephemeral_branch="generations/run/1",
        proxy_url="http://proxy.test:8888",
        no_proxy="tin.test",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError("proxy failed"), asyncio.CancelledError()])
async def test_sandbox_is_killed_on_proxy_failure_or_activity_cancellation(
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException,
) -> None:
    class FailingCommands:
        async def run(self, *args, **kwargs):
            raise failure

    order: list[str] = []

    class Files:
        async def list(self, path, **kwargs):
            raise NotFoundException("no sessions yet")

    class FakeSandbox:
        def __init__(self) -> None:
            self.commands = FailingCommands()
            self.files = Files()
            self.killed = False

        async def kill(self) -> None:
            order.append("kill")
            self.killed = True

    sandbox = FakeSandbox()

    async def connect(*args, **kwargs):
        return sandbox

    async def sink(capture) -> None:
        order.append("rollouts")
        assert capture.sandbox_id == "sandbox-1"
        assert capture.files == ()
        assert capture.error is None

    monkeypatch.setattr("tin_lite.e2b_runtime.AsyncSandbox.connect", connect)
    runtime = E2BRuntime(
        api_key="e2b-test",  # noqa: S106
        template="tin-lite-test",
        timeout_seconds=10,
        egress_allow_hosts=(),
    )

    with pytest.raises(type(failure)):
        await runtime.run_procedure_and_kill(
            sandbox_id="sandbox-1",
            run_input=SandboxProcedureInput(
                **{**asdict(sandbox_input()), "rollout_sink": sink},
                context={},
                output_path="report.md",
                output_max_bytes=1000,
                isolated=True,
                usage_sink=AsyncMock(),
                api_url="https://tin.test/relay",
                api_grant="synthetic-relay-grant",
            ),
        )

    # The failed run's transcript is captured before the sandbox disappears.
    assert order == ["rollouts", "kill"]
    assert sandbox.killed is True


@pytest.mark.asyncio
async def test_database_outage_makes_health_check_unavailable_without_details() -> None:
    class UnavailableDatabase:
        async def ping(self) -> bool:
            raise ConnectionError("database host and credential details")

    app = FastAPI()
    app.include_router(router)
    app.state.runtime = SimpleNamespace(database=UnavailableDatabase())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")

    assert response.status_code == 503
    assert "database host" not in response.text


@pytest.mark.asyncio
async def test_absent_sandbox_is_the_only_idempotent_cleanup_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def connect(*args, **kwargs):
        raise SandboxNotFoundException("sandbox is absent")

    monkeypatch.setattr("tin_lite.e2b_runtime.AsyncSandbox.connect", connect)
    runtime = E2BRuntime(
        api_key="e2b-test",  # noqa: S106
        template="tin-lite-test",
        timeout_seconds=10,
        egress_allow_hosts=(),
    )

    assert await runtime.is_running("sandbox-1") is False
    await runtime.kill("sandbox-1")


@pytest.mark.asyncio
async def test_e2b_outage_is_not_misreported_as_sandbox_absence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def connect(*args, **kwargs):
        raise ConnectionError("E2B control plane unavailable")

    monkeypatch.setattr("tin_lite.e2b_runtime.AsyncSandbox.connect", connect)
    runtime = E2BRuntime(
        api_key="e2b-test",  # noqa: S106
        template="tin-lite-test",
        timeout_seconds=10,
        egress_allow_hosts=(),
    )

    with pytest.raises(ConnectionError, match="control plane unavailable"):
        await runtime.is_running("sandbox-1")
    with pytest.raises(ConnectionError, match="control plane unavailable"):
        await runtime.kill("sandbox-1")
