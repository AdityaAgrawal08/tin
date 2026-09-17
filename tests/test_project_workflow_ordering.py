from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
from test_private_workflows import ACTOR, app, mcp, structured
from test_procedure_publication import publication_db as publication_db

from tin_lite.catalog import BUILTIN_WORKFLOWS


async def test_saved_workflows_are_newest_first_in_http_and_mcp(publication_db, monkeypatch):
    db = publication_db
    project = await db.create_project(name="Ordering proof", state_repo_id="projects/ordering")
    other = await db.create_project(name="Other project", state_repo_id="projects/other")
    await db.record_tin_user(ACTOR)
    await db.grant_project_membership(project_id=project.id, clerk_user_id=ACTOR)
    spec = next(item for item in BUILTIN_WORKFLOWS if item.key == "project.weekly_brief")
    await db.upsert_registry_workflow(
        workflow_id=spec.id,
        key=spec.key,
        title=spec.title,
        description=spec.description,
        executor=spec.executor,
        definition_repo_id="registry/workflows",
        definition_path=spec.definition_path,
        current_commit_sha="d" * 40,
        version_label=spec.version_label,
        definition=spec.definition,
    )

    async def save(name, owner=project):
        return await db.create_project_workflow(
            project_id=owner.id,
            workflow_id=spec.id,
            definition_commit_sha="d" * 40,
            name=name,
            inputs={},
            input_schema=spec.input_schema,
            schedule=None,
            request_id=uuid4(),
            created_by_clerk_user_id=ACTOR,
        )

    older, newer, tied, archived = [
        await save(name) for name in ("older", "newer", "tied", "archived")
    ]
    await save("Not in this project", other)
    for item in (older, newer, tied, archived):
        await db.pool.execute(
            "UPDATE project_workflows SET created_at=$2, updated_at=$3 WHERE id=$1",
            item.id,
            datetime(2026, 9, 9 if item.id == older.id else 10, tzinfo=UTC),
            datetime(2026, 9, 12 if item.id == older.id else 11, tzinfo=UTC),
        )
    await db.archive_project_workflow(
        project_workflow_id=archived.id,
        project_id=project.id,
        expected_settings_revision=archived.settings_revision,
        clerk_user_id=ACTOR,
        workflow_key=spec.key,
        workflow_title=archived.name,
    )
    assert (
        await db.pool.fetchval("SELECT status FROM project_workflows WHERE id=$1", archived.id)
        == "archived"
    )
    expected = [str(item) for item in sorted((newer.id, tied.id), reverse=True)] + [str(older.id)]
    assert [
        str(item.id) for item in await db.list_project_workflows(project_id=project.id)
    ] == expected

    f = SimpleNamespace(
        settings=SimpleNamespace(
            switchboard_public_url="https://tin.test", clerk_frontend_api_url="https://clerk.test"
        ),
        runtime=SimpleNamespace(database=db),
    )
    server = mcp(f, monkeypatch)
    result = structured(
        await server.call_tool("list_project_workflows", {"project_id": str(project.id)})
    )
    assert [item["id"] for item in result["result"]] == expected
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(f)), base_url="https://tin.test"
    ) as client:
        response = await client.get(f"/api/projects/{project.id}/workflows")
        assert response.status_code == 200
        assert [item["id"] for item in response.json()] == expected
