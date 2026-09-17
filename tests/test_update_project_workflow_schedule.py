from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from tin_lite.mcp_server import create_mcp_app
from tin_lite.schedules import WorkflowSchedule

WEEKLY = WorkflowSchedule.model_validate(
    {
        "cadence": "weekly",
        "weekdays": ["monday"],
        "local_time": "09:00",
        "timezone": "America/Los_Angeles",
    }
).model_dump(mode="json")


@pytest.fixture
def harness(monkeypatch):
    project_id, workflow_id = uuid4(), uuid4()
    token = SimpleNamespace(subject="member", scopes=["openid"], client_id="test_client")
    monkeypatch.setattr("tin_lite.mcp_server.get_access_token", lambda: token)
    existing = SimpleNamespace(
        id=workflow_id,
        project_id=project_id,
        workflow_id=uuid4(),
        workflow_key="visibility.audit",
        workflow_title="Audit AI visibility",
        name="Audit AI visibility",
        inputs={"target": "with.md"},
        input_schema={},
        schedule=dict(WEEKLY),
        status="active",
        temporal_schedule_id="tin-lite-project-workflow:x",
        settings_revision=1,
        definition_commit_sha="a" * 40,
    )

    async def access(*, project_id, clerk_user_id):
        return True

    update = AsyncMock(return_value=existing)
    db = SimpleNamespace(
        has_project_access=access,
        record_mcp_usage=AsyncMock(),
        record_tin_user=AsyncMock(),
        get_project_workflow=AsyncMock(return_value=existing),
        get_workflow=AsyncMock(return_value=SimpleNamespace(definition={})),
        update_project_workflow=update,
    )
    runtime = SimpleNamespace(database=db, storage=SimpleNamespace(), temporal=None)
    settings = SimpleNamespace(
        switchboard_public_url="https://tin.test",
        clerk_frontend_api_url="https://clerk.tin.test",
    )

    async def contract(**kwargs):
        return kwargs["workflow"]

    monkeypatch.setattr("tin_lite.workflow_definitions.resolve_execution_contract", contract)
    monkeypatch.setattr(
        "tin_lite.mcp_server._mcp_schedule",
        lambda definition, value: WorkflowSchedule.model_validate(value) if value else None,
    )
    monkeypatch.setattr(
        "tin_lite.mcp_server.normalize_workflow_inputs",
        lambda *, schema, project_id, inputs: dict(inputs),
    )

    async def sync(**kwargs):
        return kwargs["configured"]

    monkeypatch.setattr("tin_lite.mcp_server._sync_mcp_project_workflow", sync)
    monkeypatch.setattr(
        "tin_lite.mcp_server._mcp_project_workflow_view", lambda configured: {"ok": True}
    )
    server, _ = create_mcp_app(settings=settings, auth=SimpleNamespace(), runtime=lambda: runtime)
    arguments = {
        "project_id": str(project_id),
        "project_workflow_id": str(workflow_id),
        "name": "Audit AI visibility",
        "inputs": {"target": "with.md, markdown for agents"},
        "expected_settings_revision": 1,
    }
    return server, arguments, update


async def test_omitted_schedule_keeps_the_saved_one(harness) -> None:
    server, arguments, update = harness
    await server.call_tool("update_project_workflow", arguments)
    saved = update.await_args.kwargs
    assert saved["schedule"] == WEEKLY
    assert "schedule" not in saved["changed_fields"]


async def test_clear_schedule_removes_it_on_purpose(harness) -> None:
    server, arguments, update = harness
    await server.call_tool("update_project_workflow", {**arguments, "clear_schedule": True})
    saved = update.await_args.kwargs
    assert saved["schedule"] is None
    assert "schedule" in saved["changed_fields"]


async def test_given_schedule_replaces_the_saved_one(harness) -> None:
    server, arguments, update = harness
    daily = {"cadence": "daily", "local_time": "08:00", "timezone": "America/Los_Angeles"}
    await server.call_tool("update_project_workflow", {**arguments, "schedule": daily})
    saved = update.await_args.kwargs
    assert saved["schedule"]["cadence"] == "daily"
    assert "schedule" in saved["changed_fields"]
