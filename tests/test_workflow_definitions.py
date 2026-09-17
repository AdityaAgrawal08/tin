import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from test_procedure_publication import publication_db as publication_db

from tin_lite.activities import TinActivities
from tin_lite.api import router
from tin_lite.auth import AuthContext, require_user
from tin_lite.catalog import BUILTIN_WORKFLOWS
from tin_lite.mcp_server import create_mcp_app
from tin_lite.procedures import load_pinned_codex_procedure
from tin_lite.run_service import start_workflow_run
from tin_lite.workflow_definitions import resolve_execution_contract
from tin_lite.workflow_inputs import normalize_workflow_inputs

A, B = "a" * 40, "b" * 40
ACTOR = "user_phase1"
SCHEDULE = {"cadence": "weekly", "weekdays": ["monday"], "local_time": "09:00", "timezone": "UTC"}


async def fixture(db):
    builtin = next(w for w in BUILTIN_WORKFLOWS if w.key == "research.deep_dive")
    definition, resources = builtin.definition_and_resource_files()
    definition["human_review"] = {"eligible": True}
    definition["system_wiki"] = {"repo_id": "wiki/system", "path": "guide.md", "commit_sha": A}
    definition["input_schema"]["properties"]["depth"]["default"] = "focused"
    project = await db.create_project(name="Version proof", state_repo_id="projects/version-proof")
    await db.record_tin_user(ACTOR)
    await db.grant_project_membership(project_id=project.id, clerk_user_id=ACTOR)
    values = dict(
        workflow_id=builtin.id,
        key=builtin.key,
        executor=builtin.executor,
        title=builtin.title,
        description=builtin.description,
        definition_repo_id="registry/workflows",
        definition_path=builtin.definition_path,
        current_commit_sha=A,
        version_label="A",
        definition=definition,
    )
    await db.upsert_registry_workflow(**values)
    workflow = await db.get_workflow(builtin.id)
    inputs = normalize_workflow_inputs(
        schema=definition["input_schema"],
        project_id=project.id,
        inputs={"question": "Test the selected contract"},
    )
    configured = await db.create_project_workflow(
        project_id=project.id,
        workflow_id=builtin.id,
        definition_commit_sha=A,
        name="Version A",
        inputs=inputs,
        input_schema=definition["input_schema"],
        schedule=SCHEDULE,
        request_id=uuid4(),
        created_by_clerk_user_id=ACTOR,
    )
    configured = await db.project_workflow_synced(
        project_workflow_id=configured.id,
        temporal_schedule_id=f"tin-lite-project-workflow:{configured.id}",
        next_run_at=None,
    )
    snapshots = {A: {builtin.definition_path: json.dumps(definition).encode(), **resources}}

    async def read(*, repo_id, commit_sha, path):
        assert repo_id == "registry/workflows"
        return snapshots[commit_sha][path]

    storage = SimpleNamespace(read_canonical_artifact=AsyncMock(side_effect=read))
    settings = SimpleNamespace(
        billing_hosted_defaults_enabled=True,
        task_queue="version-proof",
        switchboard_public_url="https://tin.test",
        clerk_frontend_api_url="https://clerk.tin.test",
    )
    runtime = SimpleNamespace(
        database=db,
        storage=storage,
        temporal=SimpleNamespace(
            start_workflow=AsyncMock(),
            get_schedule_handle=Mock(return_value=SimpleNamespace(update=AsyncMock())),
        ),
        integrations=SimpleNamespace(ensure_requirements=AsyncMock()),
    )
    return SimpleNamespace(
        db=db,
        builtin=builtin,
        project=project,
        definition=definition,
        resources=resources,
        values=values,
        workflow=workflow,
        configured=configured,
        snapshots=snapshots,
        runtime=runtime,
        storage=storage,
        settings=settings,
    )


async def activate_b(f):
    definition = deepcopy(f.definition)
    definition.pop("human_review")
    definition["version"] = "B"
    definition["schedule_modes"] = ["on_demand"]
    definition["system_wiki"]["commit_sha"] = B
    definition["input_schema"]["properties"]["depth"]["default"] = "extensive"
    definition["procedure"]["output"]["path"] = "reports/NEW.md"
    f.snapshots[B] = {
        f.builtin.definition_path: json.dumps(definition).encode(),
        **f.resources,
        definition["procedure"]["prompt_path"]: b"New version instructions",
    }
    await f.db.upsert_registry_workflow(
        **{**f.values, "definition": definition, "current_commit_sha": B, "version_label": "B"}
    )
    return await f.db.get_workflow(f.builtin.id)


def http_app(f):
    app = FastAPI()
    app.include_router(router)
    app.state.runtime, app.state.settings = f.runtime, f.settings
    app.dependency_overrides[require_user] = lambda: AuthContext(
        clerk_user_id=ACTOR,
        token_type="session_token",  # noqa: S106 — token category, not a credential
    )
    return app


def mcp(f, monkeypatch):
    token = SimpleNamespace(subject=ACTOR, scopes=["openid"], client_id="test_client")
    monkeypatch.setattr("tin_lite.mcp_server.get_access_token", lambda: token)
    server, _ = create_mcp_app(
        settings=f.settings, auth=SimpleNamespace(), runtime=lambda: f.runtime
    )
    return server


@pytest.mark.parametrize("surface", ["http", "mcp", "schedule", "parent_child"])
async def test_saved_a_after_b_uses_the_whole_a_contract(publication_db, monkeypatch, surface):
    f = await fixture(publication_db)
    latest = await activate_b(f)
    if surface == "http":
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=http_app(f)), base_url="http://test"
        ) as client:
            response = await client.post(
                f"/api/projects/{f.project.id}/workflows/{f.configured.id}/runs"
            )
            assert response.status_code == 202, response.text
    elif surface == "mcp":
        await mcp(f, monkeypatch).call_tool(
            "start_project_workflow",
            {
                "project_id": str(f.project.id),
                "project_workflow_id": str(f.configured.id),
                "request_id": str(uuid4()),
            },
        )
    elif surface == "schedule":
        activities = TinActivities(
            database=f.db, storage=f.storage, sandboxes=None, settings=f.settings
        )
        payload = await activities.dispatch_scheduled_workflow(
            {
                "project_workflow_id": str(f.configured.id),
                "scheduled_for": datetime.now(UTC).isoformat(),
                "occurrence_id": "a-occurrence",
            }
        )
        assert set(payload) == {"run_id", "executor", "temporal_workflow_id"}
    else:
        await start_workflow_run(
            runtime=f.runtime,
            settings=f.settings,
            workflow=latest,
            project_id=f.project.id,
            started_by_clerk_user_id=ACTOR,
            input_payload=f.configured.inputs,
            project_workflow_id=f.configured.id,
            definition_commit_sha=A,
            input_schema=f.definition["input_schema"],
            _prepare_only=True,
        )
        f.runtime.temporal.start_workflow.assert_not_awaited()
    run_id = await f.db.pool.fetchval(
        "SELECT id FROM workflow_runs WHERE project_workflow_id = $1", f.configured.id
    )
    run = await f.db.get_run(run_id)
    assert run.definition_commit_sha == A
    assert run.system_wiki_commit_sha == A and run.review_required is True
    assert run.input["depth"] == "focused"
    spec = await load_pinned_codex_procedure(
        storage=f.storage,
        repo_id="registry/workflows",
        commit_sha=run.definition_commit_sha,
        definition_path=f.builtin.definition_path,
    )
    assert spec.output_path == f.definition["procedure"]["output"]["path"]
    assert spec.prompt.encode() == f.resources[f.definition["procedure"]["prompt_path"]]
    assert (await f.db.get_workflow(f.builtin.id)).definition == latest.definition


@pytest.mark.parametrize("surface", ["http", "mcp"])
async def test_editing_a_uses_a_schedule_rules_not_b(publication_db, monkeypatch, surface):
    f = await fixture(publication_db)
    await activate_b(f)
    inputs = {**f.configured.inputs, "question": "Updated future inputs"}
    if surface == "http":
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=http_app(f)), base_url="http://test"
        ) as client:
            response = await client.put(
                f"/api/projects/{f.project.id}/workflows/{f.configured.id}",
                json={
                    "name": "Edited A",
                    "inputs": inputs,
                    "schedule": SCHEDULE,
                    "expected_settings_revision": 1,
                },
            )
            assert response.status_code == 200, response.text
    else:
        await mcp(f, monkeypatch).call_tool(
            "update_project_workflow",
            {
                "project_id": str(f.project.id),
                "project_workflow_id": str(f.configured.id),
                "name": "Edited A",
                "inputs": inputs,
                "schedule": SCHEDULE,
                "expected_settings_revision": 1,
            },
        )
    saved = await f.db.get_project_workflow(f.configured.id)
    assert saved.definition_commit_sha == A and saved.inputs == inputs
    assert saved.schedule == {**SCHEDULE, "start_at": None, "end_at": None}
    assert saved.settings_revision == 2


async def test_repeat_request_after_activation_recovers_original_revision(publication_db):
    f = await fixture(publication_db)
    options = dict(
        runtime=f.runtime,
        settings=f.settings,
        project_id=f.project.id,
        started_by_clerk_user_id=ACTOR,
        input_payload={"question": "same request"},
        start_idempotency_key="same-request",
    )
    first = await start_workflow_run(workflow=f.workflow, **options)
    await f.db.pool.execute("UPDATE workflow_runs SET status = 'running' WHERE id = $1", first.id)
    latest = await activate_b(f)
    repeated = await start_workflow_run(workflow=latest, **options)
    assert repeated.id == first.id and repeated.definition_commit_sha == A
    assert repeated.input["depth"] == "focused"
    f.runtime.temporal.start_workflow.assert_awaited_once()
    with pytest.raises(RuntimeError, match="different input"):
        await start_workflow_run(
            workflow=latest, **{**options, "input_payload": {"question": "different"}}
        )


async def test_resolver_fails_closed_before_source_reads_and_on_wrong_schema(publication_db):
    f = await fixture(publication_db)
    latest = await activate_b(f)
    with pytest.raises(LookupError):
        await resolve_execution_contract(
            storage=f.storage,
            workflow=replace(latest, project_id=uuid4()),
            project_id=f.project.id,
            revision=A,
        )
    f.storage.read_canonical_artifact.assert_not_awaited()
    with pytest.raises(ValueError, match="saved input schema"):
        await resolve_execution_contract(
            storage=f.storage,
            workflow=latest,
            project_id=f.project.id,
            revision=A,
            input_schema=latest.definition["input_schema"],
        )
    f.snapshots[A][f.builtin.definition_path] = b'{"key":"different","executor":"codex.procedure"}'
    with pytest.raises(ValueError, match="workflow identity"):
        await resolve_execution_contract(
            storage=f.storage, workflow=latest, project_id=f.project.id, revision=A
        )


@pytest.mark.parametrize(
    "change",
    [
        {"definition_path": "moved.json"},
        {"definition_repo_id": "other/repository"},
        {"executor": "project.task"},
    ],
)
async def test_published_source_identity_cannot_move(publication_db, change):
    f = await fixture(publication_db)
    with pytest.raises(RuntimeError, match="different workflow or source"):
        await f.db.upsert_registry_workflow(**{**f.values, **change})
