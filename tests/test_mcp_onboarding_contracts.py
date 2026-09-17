"""Calls an agent can copy directly from onboarding; no external services."""

from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from test_private_workflows import ACTOR, activate, fixture, mcp, structured
from test_procedure_publication import publication_db as publication_db
from test_service_billing import install


@pytest.fixture
async def account(publication_db, monkeypatch):
    f = await fixture(publication_db)
    await f.db.grant_workspace_membership(workspace_id=f.project.workspace_id, clerk_user_id=ACTOR)
    f.storage.ensure_repo = AsyncMock()
    f.server = mcp(f, monkeypatch)
    return f


async def call(f, tool_name, **arguments):
    return structured(await f.server.call_tool(tool_name, arguments))


async def test_name_only_creation_in_one_workspace_and_explicit_retry(account):
    f = account
    project = await call(f, "create_project", name="Example business")
    assert project["workspace_id"] == str(f.project.workspace_id)
    assert project["name"] == "Example business"
    assert UUID(project["request_id"])
    replay = await call(
        f, "create_project", name="Example business", request_id=project["request_id"]
    )
    assert replay == project
    assert len(await f.db.list_projects_for_user(ACTOR)) == 2
    with pytest.raises(ToolError, match="already used for another project"):
        await call(f, "create_project", name="Different business", request_id=project["request_id"])


async def test_workspace_choice_is_explicit_when_ambiguous_and_never_infers_from_project_access(
    account,
):
    f = account
    other = await f.db.create_project(name="Other", state_repo_id="projects/other")
    await f.db.grant_workspace_membership(workspace_id=other.workspace_id, clerk_user_id=ACTOR)
    with pytest.raises(ToolError, match="Choose workspace_id") as error:
        await call(f, "create_project", name="A business")
    assert str(f.project.workspace_id) in str(error.value)
    assert str(other.workspace_id) in str(error.value)
    f.storage.ensure_repo.assert_not_called()
    project = await call(
        f, "create_project", name="A business", workspace_id=str(other.workspace_id)
    )
    assert project["workspace_id"] == str(other.workspace_id)
    await f.db.pool.execute("DELETE FROM workspace_memberships WHERE clerk_user_id=$1", ACTOR)
    f.storage.ensure_repo.reset_mock()
    with pytest.raises(ToolError, match="No administered workspace"):
        await call(f, "create_project", name="No authority")
    with pytest.raises(ToolError, match="workspace not found"):
        await call(
            f, "create_project", name="No authority", workspace_id=str(f.project.workspace_id)
        )
    f.storage.ensure_repo.assert_not_called()


async def test_uuid_requirements_are_in_the_schema_and_invalid_values_have_no_effect(account):
    f = account
    tools = {tool.name: tool for tool in await f.server.list_tools()}
    assert tools["create_project"].input_schema["required"] == ["name"]
    for tool, fields in {
        "create_project": ["workspace_id", "request_id"],
        "get_workflow": ["project_id", "workflow_id"],
    }.items():
        for field in fields:
            schema = tools[tool].input_schema["properties"][field]
            assert {"format": "uuid", "type": "string"} in schema["anyOf"]
            assert schema["description"]
    for field in ["workspace_id", "request_id"]:
        with pytest.raises(ToolError, match="UUID"):
            await call(f, "create_project", name="Invalid", **{field: "not-a-uuid"})
    f.storage.ensure_repo.assert_not_called()


async def test_onboarding_identifier_and_ready_to_call_inspection_both_work(account):
    f = account
    workflow = await install(f, "growth.onboarding")
    started = await call(f, "get_started", project_id=str(f.project.id))
    first = started["first_workflow"]
    assert first["id"] == str(workflow.id)
    generic = await call(f, "get_workflow", workflow_id=first["id"])
    assert generic["key"] == first["key"]
    assert generic["readiness"] is None and generic["project_id"] is None
    assert "preparation" not in generic
    assert "input_schema" in generic
    inspect = first["inspect"]
    scoped = await call(f, inspect["name"], **inspect["arguments"])
    assert scoped["project_id"] == str(f.project.id)
    assert scoped["readiness"] is not None
    for key in [first["key"], first["id"]]:
        old_client = await call(f, "get_workflow", project_id=str(f.project.id), workflow_key=key)
        assert old_client == scoped
    by_key = await call(f, "get_workflow", workflow_key=first["key"])
    assert by_key == generic
    with pytest.raises(ToolError, match="not both"):
        await call(f, "get_workflow", workflow_id=first["id"], workflow_key=first["key"])
    with pytest.raises(ToolError, match="Supply workflow_id"):
        await call(f, "get_workflow")
    with pytest.raises(ToolError, match="workflow not found"):
        await call(f, "get_workflow", workflow_id=str(uuid4()))
    f.runtime.temporal.start_workflow.assert_not_called()


async def test_private_id_inspection_keeps_membership_boundary(account, monkeypatch):
    f = account
    private = await activate(f)
    result = await call(f, "get_workflow", workflow_id=private["workflow_id"])
    assert result["scope"] == "project" and result["project_id"] == str(f.project.id)
    other = await f.db.create_project(name="Other", state_repo_id="projects/other")
    await f.db.grant_project_membership(project_id=other.id, clerk_user_id=ACTOR)
    with pytest.raises(ToolError, match="workflow not found"):
        await call(f, "get_workflow", project_id=str(other.id), workflow_id=private["workflow_id"])
    f.server = mcp(f, monkeypatch, actor="user_OutsideProject")
    with pytest.raises(ToolError, match="workflow not found"):
        await call(f, "get_workflow", workflow_id=private["workflow_id"])
