from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest

from tin_lite.domain import RunToolGrant
from tin_lite.run_tools import RunToolTokenVerifier, create_run_tools_app

ROOT = Path(__file__).parents[1]
RUN_ID = UUID("00000000-0000-4000-8000-0000000000bb")
PROJECT_ID = UUID("00000000-0000-4000-8000-0000000000aa")
CONNECTION_ID = UUID("00000000-0000-4000-8000-0000000000ab")
TEST_GRANT = "opaque-run-grant"  # noqa: S105


class GrantDatabase:
    def __init__(self) -> None:
        self.active = True
        self.calls: list[dict] = []

    async def authorize_run_tool_grant(self, **values):
        self.calls.append(values)
        if not self.active or values["token"] != TEST_GRANT:
            return None
        capability = values.get("capability")
        capabilities = ("gmail.messages.read", "calendar.events.read", "test_identity.write")
        if capability is not None and capability not in capabilities:
            return None
        return RunToolGrant(
            project_id=PROJECT_ID,
            run_id=RUN_ID,
            connection_id=CONNECTION_ID,
            external_account_id="google-account-1",
            sandbox_id="sandbox-one",
            provider_key="workspace.google",
            capabilities=capabilities,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )


@pytest.mark.asyncio
async def test_run_tool_token_maps_only_an_active_opaque_grant() -> None:
    database = GrantDatabase()
    runtime = lambda: SimpleNamespace(database=database)  # noqa: E731
    verifier = RunToolTokenVerifier(runtime=runtime, resource="https://tin.test/run-tools")

    assert await verifier.verify_token("wrong") is None
    accepted = await verifier.verify_token(TEST_GRANT)
    assert accepted is not None
    assert accepted.subject == str(RUN_ID)
    assert accepted.client_id == "sandbox-one"
    assert accepted.scopes == [
        "gmail.messages.read",
        "calendar.events.read",
        "test_identity.write",
    ]

    database.active = False
    assert await verifier.verify_token(TEST_GRANT) is None


@pytest.mark.asyncio
async def test_run_tools_expose_only_declared_run_bound_capabilities() -> None:
    database = GrantDatabase()
    server, app = create_run_tools_app(
        settings=SimpleNamespace(switchboard_public_url="https://tin.test"),
        runtime=lambda: SimpleNamespace(database=database),
    )

    assert {tool.name for tool in await server.list_tools()} == {
        "search_gmail",
        "get_gmail_thread",
        "list_calendar_events",
        "record_test_identity_status",
        "search_sms",
        "request_service",
        "call_service",
    }
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://tin.test"
        ) as client:
            anonymous = await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            )
    assert anonymous.status_code == 401


def test_run_tool_grant_is_fenced_and_sandbox_never_receives_provider_credentials() -> None:
    migration = (ROOT / "migrations" / "013_google_workspace.sql").read_text()
    identities = (ROOT / "migrations" / "015_project_test_identities.sql").read_text()
    assert "CREATE TABLE project_test_identities" in identities
    assert "password_ciphertext bytea" in identities
    assert "UNIQUE (created_by_run_id)" in identities
    assert "password text" not in identities
    database_source = (ROOT / "src" / "tin_lite" / "db.py").read_text()
    sandbox_script = (ROOT / "sandbox" / "run_procedure.sh").read_text()

    assert "run.sandbox_id = grant_row.sandbox_id" in database_source
    assert "run.generation = grant_row.generation" in database_source
    assert "run.fencing_token = grant_row.fencing_token" in database_source
    assert "run.lease_active = true" in database_source
    assert "connection_id uuid NOT NULL" in migration
    assert "external_account_id text NOT NULL" in migration
    assert "CREATE TABLE run_tool_grants" in migration
    assert "TIN_RUN_TOOLS_GRANT" in sandbox_script
    assert "-u TIN_LITE_GOOGLE_OAUTH_CLIENT_SECRET" in sandbox_script
    assert "refresh_token" not in sandbox_script
    assert "password_ciphertext" not in sandbox_script
