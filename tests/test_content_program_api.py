from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from mcp.server.mcpserver.exceptions import ToolError

from tin_lite.auth import AuthContext, require_user
from tin_lite.content_plan import empty_plan
from tin_lite.content_program_api import router
from tin_lite.content_programs import ContentPrograms
from tin_lite.mcp_server import create_mcp_app


@pytest.mark.asyncio
async def test_content_program_http_mcp_membership_and_shared_edit(monkeypatch):
    project_id, program_id, request_id = uuid4(), uuid4(), uuid4()
    token = SimpleNamespace(subject="outsider", scopes=["openid"], client_id="test_client")
    monkeypatch.setattr("tin_lite.mcp_server.get_access_token", lambda: token)

    async def access(*, project_id, clerk_user_id):
        return clerk_user_id == "member"

    db = SimpleNamespace(
        has_project_access=access, record_mcp_usage=AsyncMock(), record_tin_user=AsyncMock()
    )
    runtime = SimpleNamespace(database=db, storage=SimpleNamespace())
    settings = SimpleNamespace(
        switchboard_public_url="https://tin.test",
        clerk_frontend_api_url="https://clerk.tin.test",
    )
    server, _ = create_mcp_app(settings=settings, auth=SimpleNamespace(), runtime=lambda: runtime)
    app = FastAPI()
    app.include_router(router)
    app.state.runtime = runtime
    app.dependency_overrides[require_user] = lambda: AuthContext(
        clerk_user_id=token.subject,
        token_type="session_token",  # noqa: S106
    )
    from tin_lite.project_files import ProjectFileCommitResult

    save = AsyncMock(
        return_value=ProjectFileCommitResult(project_id, request_id, "b" * 40, (), "commit")
    )
    monkeypatch.setattr(ContentPrograms, "save", save)
    path = f"/api/projects/{project_id}/content-programs/{program_id}"
    plan = empty_plan(
        program_id,
        {
            "audit_run_id": str(uuid4()),
            "keyword_run_id": str(uuid4()),
            "start_date": "2026-09-08",
            "duration": "6_months",
        },
        {"host": "example.com", "market": "US"},
    )
    body = {"request_id": str(request_id), "expected_revision": "a" * 40, "plan": plan}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://tin.test"
    ) as client:
        for suffix in ("", "/plan"):
            assert (await client.get(path + suffix)).status_code == 404
        assert (await client.put(path + "/plan", json=body)).status_code == 404
        arguments = {
            "project_id": str(project_id),
            "project_workflow_id": str(program_id),
            **body,
        }
        with pytest.raises(ToolError, match="project not found"):
            await server.call_tool("edit_content_plan", arguments)
        save.assert_not_awaited()
        token.subject = "member"
        assert (await client.put(path + "/plan", json=body)).status_code == 200
        await server.call_tool("edit_content_plan", arguments)
        assert save.await_count == 2
        http_call, mcp_call = (call.kwargs for call in save.await_args_list)
        assert http_call == {key: value for key, value in mcp_call.items() if key != "client_id"}
        assert mcp_call["client_id"] == "test_client"
