"""Opt-in real E2B cleanup, disposable Postgres, no model or production project writes.

Set TIN_LITE_LIVE_E2B_STOP_TEST=1 and TIN_LITE_TEST_DATABASE_DSN to a disposable database.
Uses only E2B_API_KEY from the operator environment or .env; it never enters the sandbox.
Temporal cancellation is stubbed: this proves MCP → SQL → real E2B cleanup,
not a paid production workflow or private-auth isolation.
"""

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from dotenv import dotenv_values
from e2b import AsyncSandbox, SandboxNotFoundException
from test_procedure_control import fixture
from test_procedure_publication import publication_db as publication_db

from tin_lite.e2b_runtime import E2BRuntime
from tin_lite.mcp_server import create_mcp_app

pytestmark = pytest.mark.skipif(
    os.environ.get("TIN_LITE_LIVE_E2B_STOP_TEST") != "1",
    reason="opt-in paid E2B cleanup proof",
)


async def test_mcp_stop_kills_real_compute_and_duplicate_is_harmless(publication_db, monkeypatch):
    api_key = os.environ.get("E2B_API_KEY") or dotenv_values(".env").get("E2B_API_KEY")
    assert api_key, "E2B_API_KEY is required"
    runner = E2BRuntime(
        api_key=api_key,
        template="tin-lite-codex",
        timeout_seconds=120,
        egress_allow_hosts=(),
    )
    f = await fixture(publication_db, monkeypatch)
    f.runtime.sandboxes = runner
    token = SimpleNamespace(subject=f.member, scopes=["openid"], client_id="cleanup-proof")
    monkeypatch.setattr("tin_lite.mcp_server.get_access_token", lambda: token)
    monkeypatch.setattr(f.db, "record_mcp_usage", AsyncMock())
    monkeypatch.setattr(f.db, "record_tin_user", AsyncMock())
    server, _ = create_mcp_app(
        settings=SimpleNamespace(
            switchboard_public_url="https://tin.test",
            clerk_frontend_api_url="https://clerk.test",
        ),
        auth=SimpleNamespace(),
        runtime=lambda: f.runtime,
    )
    sandbox = await AsyncSandbox.create(
        "tin-lite-codex",
        api_key=api_key,
        timeout=120,
        metadata={"purpose": "tin-lite-procedure-stop-proof"},
        network={"deny_out": lambda context: [context.all_traffic]},
    )
    try:
        await f.db.pool.execute(
            "UPDATE workflow_runs SET sandbox_id=$2 WHERE id=$1",
            f.run.id,
            sandbox.sandbox_id,
        )
        # Synthetic idle work. No Codex, OAuth cache, model call or project checkout.
        await sandbox.commands.run("sleep 90", background=True, timeout=100)
        results = await asyncio.gather(
            *(server.call_tool("stop_procedure", {"run_id": str(f.run.id)}) for _ in range(2))
        )
        for result in results:
            facts = result.structured_content
            assert facts["status"] == "stopped"
            assert not facts["cleanup_pending"] and not facts["cancellation_pending"]
        with pytest.raises(SandboxNotFoundException):
            await AsyncSandbox.connect(sandbox.sandbox_id, api_key=api_key)
    finally:
        await runner.kill(sandbox.sandbox_id)
