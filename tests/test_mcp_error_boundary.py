"""Every anticipated failure crosses the MCP boundary with its text; crashes stay masked."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError

from tin_lite.domain import SideEffectConflictError
from tin_lite.mcp_errors import BOUNDARY_MARKER, GuardedMCPServer, tool_error
from tin_lite.mcp_server import create_mcp_app
from tin_lite.output_resolution import OutputResolutionError
from tin_lite.project_files import StaleProjectRevisionError
from tin_lite.workflow_prerequisites import PrerequisiteError

MEMBER = "user_member"
OUTSIDER = "user_outsider"
REVISION = "a" * 40


def harness(monkeypatch, *, subject=MEMBER, scopes=("openid",), token_present=True):
    project = SimpleNamespace(id=uuid4(), canonical_branch="main", state_repo_id="repo")
    db = SimpleNamespace(
        has_project_access=AsyncMock(side_effect=lambda **kw: kw["clerk_user_id"] == MEMBER),
        record_mcp_usage=AsyncMock(),
        record_tin_user=AsyncMock(),
        get_project=AsyncMock(return_value=project),
    )
    runtime = SimpleNamespace(
        database=db,
        project_files=SimpleNamespace(
            commit=AsyncMock(side_effect=StaleProjectRevisionError("project revision is stale"))
        ),
    )
    token = SimpleNamespace(subject=subject, scopes=list(scopes), client_id="client_test")
    monkeypatch.setattr(
        "tin_lite.mcp_server.get_access_token", lambda: token if token_present else None
    )
    server, _ = create_mcp_app(
        settings=SimpleNamespace(
            switchboard_public_url="https://tin.test",
            clerk_frontend_api_url="https://clerk.test",
            billing_enabled=True,
        ),
        auth=SimpleNamespace(),
        runtime=lambda: runtime,
    )
    return SimpleNamespace(server=server, project=project, runtime=runtime, token=token)


async def failure(server, tool: str, arguments: dict) -> str:
    with pytest.raises(ToolError) as caught:
        await server.call_tool(tool, arguments)
    assert not isinstance(caught.value, UnexpectedToolError), repr(caught.value.__cause__)
    return str(caught.value)


def commit_args(changes):
    return {
        "project_id": str(uuid4()),
        "expected_revision": REVISION,
        "request_id": str(uuid4()),
        "message": "tick the plan",
        "changes": changes,
    }


async def test_missing_token_is_forbidden(monkeypatch):
    h = harness(monkeypatch, token_present=False)
    text = await failure(h.server, "list_projects", {})
    assert "forbidden: authenticated Tin user required" in text


async def test_missing_scope_is_forbidden(monkeypatch):
    h = harness(monkeypatch, scopes=())
    text = await failure(h.server, "list_projects", {})
    assert "forbidden: OAuth scope openid is required" in text


async def test_outsider_reads_not_found(monkeypatch):
    h = harness(monkeypatch, subject=OUTSIDER)
    text = await failure(h.server, "list_project_files", {"project_id": str(h.project.id)})
    assert "not_found: project not found" in text


async def test_commit_with_wrong_keys_names_the_field(monkeypatch):
    h = harness(monkeypatch)
    text = await failure(
        h.server,
        "commit_project_changes",
        commit_args([{"op": "upsert", "path": "notes.md", "content": "x"}]),
    )
    assert "changes.0.operation" in text
    assert "changes.0.op" in text


async def test_stale_revision_is_a_conflict_with_its_text(monkeypatch):
    h = harness(monkeypatch)
    text = await failure(
        h.server,
        "commit_project_changes",
        commit_args([{"operation": "upsert", "path": "notes.md", "content": "x"}]),
    )
    assert "conflict: project revision is stale" in text
    sent = h.runtime.project_files.commit.await_args.kwargs["changes"]
    assert sent == [{"operation": "upsert", "path": "notes.md", "content": "x", "new_path": None}]


async def test_bad_uuid_is_invalid_with_a_hint(monkeypatch):
    h = harness(monkeypatch)
    text = await failure(h.server, "list_project_files", {"project_id": "not-a-uuid"})
    assert "project_id must be a UUID" in text


async def test_crashes_stay_masked(monkeypatch):
    h = harness(monkeypatch)
    h.runtime.database.has_project_access = AsyncMock(side_effect=TypeError("boom"))
    with pytest.raises(UnexpectedToolError) as caught:
        await h.server.call_tool("list_project_files", {"project_id": str(h.project.id)})
    assert "boom" not in str(caught.value)


def test_tool_error_maps_the_anticipated_families():
    prerequisite = PrerequisiteError("github_required", "Connect GitHub first.")
    assert '"code": "github_required"' in str(tool_error(prerequisite))
    assert str(tool_error(OutputResolutionError("output_unavailable", "x"))) == (
        "output_unavailable: x"
    )
    assert str(tool_error(SideEffectConflictError("dup"))) == "conflict: dup"
    assert str(tool_error(LookupError("run not found"))) == "not_found: run not found"
    assert str(tool_error(PermissionError("nope"))) == "forbidden: nope"
    assert str(tool_error(ValueError("bad"))) == "invalid: bad"
    assert tool_error(KeyError("k")) is None
    assert tool_error(TypeError("bug")) is None
    assert tool_error(AssertionError()) is None
    original = ToolError("as is")
    assert tool_error(original) is original


def test_every_registered_tool_is_behind_the_boundary(monkeypatch):
    h = harness(monkeypatch)
    assert isinstance(h.server, GuardedMCPServer)
    tools = h.server._tool_manager.list_tools()
    assert len(tools) >= 60
    unguarded = [tool.name for tool in tools if not getattr(tool.fn, BOUNDARY_MARKER, False)]
    assert unguarded == []


async def test_tool_schemas_expose_the_typed_parameters(monkeypatch):
    h = harness(monkeypatch)
    schemas = {tool.name: tool.input_schema for tool in await h.server.list_tools()}
    mutation = schemas["commit_project_changes"]["$defs"]["ProjectFileMutationInput"]
    assert mutation["properties"]["operation"]["enum"] == ["upsert", "delete", "rename"]
    assert mutation["additionalProperties"] is False
    assert "ContentPlan" in schemas["edit_content_plan"]["$defs"]
    assert "WorkflowSchedule" in schemas["create_project_workflow"]["$defs"]
    assert "WorkflowSchedule" in schemas["update_project_workflow"]["$defs"]
    assert "DeliverySettings" in schemas["save_content_delivery_settings"]["$defs"]
    client = schemas["start_workflow"]["properties"]["client"]
    assert {"enum": ["claude_code", "codex", "api"], "type": "string"} in client["anyOf"]


async def test_bad_plan_names_the_missing_fields(monkeypatch):
    h = harness(monkeypatch)
    text = await failure(
        h.server,
        "edit_content_plan",
        {
            "project_id": str(h.project.id),
            "project_workflow_id": str(uuid4()),
            "request_id": str(uuid4()),
            "expected_revision": REVISION,
            "plan": {"schema_version": "content-program-v1"},
        },
    )
    assert "plan.program_id" in text
    assert "plan.batches" in text
