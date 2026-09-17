from __future__ import annotations

import base64
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from test_checkpoint_contract import FakeDatabase, authenticate, fixture_state
from test_procedure_publication import publication_db  # noqa: F401
from test_run_tools import TEST_GRANT, GrantDatabase
from test_signup_walkthrough import _walkthrough_spec

from tin_lite.api import RunCreate, _RunSafeRoute
from tin_lite.catalog import BUILTIN_WORKFLOWS
from tin_lite.e2b_runtime import SandboxRunInput, _run_secrets
from tin_lite.integrations import CredentialCipher
from tin_lite.payment_card_guard import card_secrets, reject_card_leak
from tin_lite.rollouts import redact_rollout
from tin_lite.run_payment_card import load, prepare
from tin_lite.workflow_inputs import WorkflowInputError

# Synthetic processor test number. No real payment credentials.
CARD = {
    "number": "4242424242424242",
    "name": "Example Tester",
    "expiry": "12/39",
    "security_code": "987",
    "billing_address": "123 Example Street, Test City",
}
WORKFLOW = SimpleNamespace(key="qa.signup_walkthrough", project_id=None)


def integrations():
    return SimpleNamespace(_cipher=CredentialCipher(base64.urlsafe_b64encode(b"k" * 32).decode()))


def test_optional_card_validation_never_echoes_values():
    assert prepare(None, workflow=WORKFLOW, integrations=None) is None
    for value in [
        "private-card-input",
        {**CARD, "number": "private-card-input"},
        {},
        {**CARD, "security_code": "invalid-private-code"},
    ]:
        with pytest.raises(WorkflowInputError) as error:
            prepare(value, workflow=WORKFLOW, integrations=integrations())
        assert "private-card-input" not in str(error.value)
        assert "invalid-private-code" not in str(error.value)
    with pytest.raises(WorkflowInputError, match="only supported"):
        prepare(CARD, workflow=SimpleNamespace(key="project.task"), integrations=integrations())
    with pytest.raises(WorkflowInputError, match="encryption"):
        prepare(CARD, workflow=WORKFLOW, integrations=None)
    value = prepare(CARD, workflow=WORKFLOW, integrations=integrations())
    assert CARD["number"] not in repr(value)


async def test_request_validation_does_not_echo_the_card():
    app = FastAPI()

    routes = APIRouter(route_class=_RunSafeRoute)

    @routes.post("/runs")
    async def endpoint(payload: RunCreate):
        return payload.model_dump()

    app.include_router(routes)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        for payload in [
            {"project_id": "bad", "payment_card": CARD},
            {"project_id": str(uuid4()), "payment_card": CARD, "unexpected": CARD},
        ]:
            response = await client.post("/runs", json=payload)
            assert response.status_code == 422
            assert not any(value in response.text for value in CARD.values())
        response = await client.post(
            "/runs", json={"project_id": str(uuid4()), "payment_card": CARD}
        )
        assert response.status_code == 200
        assert "payment_card" not in response.json()


async def test_direct_and_saved_start_keep_card_separate_and_require_membership(monkeypatch):
    from tin_lite import api

    project, workflow, run = fixture_state()
    workflow = replace(workflow, key=WORKFLOW.key)
    db = FakeDatabase(run=run, project=project, workflow=workflow)
    configuration_id = uuid4()

    async def configured(_id):
        return SimpleNamespace(
            id=configuration_id,
            project_id=project.id,
            workflow_id=workflow.id,
            inputs={"product_url": "https://example.test"},
            definition_commit_sha=workflow.current_commit_sha,
            input_schema={},
        )

    db.get_project_workflow = configured
    calls = []

    async def dispatch(**kwargs):
        calls.append(kwargs)
        return run

    monkeypatch.setattr(api, "dispatch_workflow_run", dispatch)
    app = FastAPI()
    app.include_router(api.router)
    authenticate(app)
    app.state.runtime = SimpleNamespace(database=db)
    app.state.settings = SimpleNamespace()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/workflows/{workflow.id}/runs",
            json={"project_id": str(project.id), "payment_card": CARD},
        )
        assert response.status_code == 202
        assert calls[-1]["payment_card"] == CARD
        assert calls[-1]["input_payload"] == {}
        assert not any(value in response.text for value in CARD.values())
        saved_path = f"/api/projects/{project.id}/workflows/{configuration_id}/runs"
        response = await client.post(saved_path, json={"payment_card": CARD})
        assert response.status_code == 202
        assert calls[-1]["payment_card"] == CARD
        assert calls[-1]["input_payload"] == {"product_url": "https://example.test"}
        response = await client.post(saved_path)
        assert response.status_code == 202 and calls[-1]["payment_card"] is None
        response = await client.post(saved_path, json={"unexpected": CARD})
        assert response.status_code == 422
        assert not any(value in response.text for value in CARD.values())
        response = await client.post(
            f"/api/workflows/{workflow.id}/runs",
            json={"project_id": str(uuid4()), "payment_card": CARD},
        )
        assert response.status_code == 404
        assert len(calls) == 3


@pytest.mark.parametrize("value", [*CARD.values(), "4242-4242-4242-4242", "4242 4242 4242 4242"])
def test_report_rejects_each_payment_field(value):
    with pytest.raises(RuntimeError, match="payment details"):
        reject_card_leak(f"# Report\n{value}".encode(), CARD)
    reject_card_leak(b"# Report\nUsed the supplied test card and cancelled the trial.", CARD)


def test_short_security_codes_are_redacted_from_runner_messages():
    params = SandboxRunInput(
        execution_key="test",
        canonical_url="https://example.test",
        canonical_auth_header="basic token",
        canonical_branch="main",
        ephemeral_url="https://example.test",
        ephemeral_auth_header="basic token",
        ephemeral_branch="test",
        proxy_url=None,
        no_proxy="",
        redact=card_secrets(CARD),
    )
    redacted, _ = redact_rollout(json.dumps(CARD).encode(), _run_secrets(params))
    assert not any(value.encode() in redacted for value in CARD.values())


def test_payment_card_only_enters_private_sandbox_context():
    identity = {"identity_id": "i", "email": "test@example.test", "password": "test-password"}
    context = _walkthrough_spec().sandbox_context(inputs={}, identity=identity, payment_card=CARD)
    assert context["payment_card"] == CARD
    assert context["inputs"] == {}
    assert "payment_card" not in _walkthrough_spec().sandbox_context(inputs={}, identity=identity)
    with pytest.raises(ValueError, match="does not accept"):
        _walkthrough_spec(workflow_key="research.deep_dive").sandbox_context(
            inputs={},
            identity=identity,
            payment_card=CARD,
        )


async def test_identity_tool_rejects_payment_details_before_saving_notes(monkeypatch):
    from mcp.server.mcpserver.exceptions import ToolError

    from tin_lite import run_payment_card, run_tools

    database = GrantDatabase()
    database.update_test_identity_status = AsyncMock()
    monkeypatch.setattr(run_payment_card, "load", AsyncMock(return_value=CARD))
    monkeypatch.setattr(run_tools, "get_access_token", lambda: SimpleNamespace(token=TEST_GRANT))
    server, _ = run_tools.create_run_tools_app(
        settings=SimpleNamespace(switchboard_public_url="https://tin.test"),
        runtime=lambda: SimpleNamespace(database=database, integrations=integrations()),
    )
    with pytest.raises(ToolError) as error:
        await server.call_tool(
            "record_test_identity_status",
            {
                "status": "active",
                "note": f"Used {CARD['number']}",
            },
        )
    assert CARD["number"] not in str(error.value)
    database.update_test_identity_status.assert_not_called()


async def test_card_is_atomic_encrypted_run_scoped_and_erased_on_terminal_state(
    publication_db,  # noqa: F811
):
    db = publication_db
    project = await db.create_project(name="Card test", state_repo_id="projects/card-test")
    builtin = next(w for w in BUILTIN_WORKFLOWS if w.key == WORKFLOW.key)
    definition, _ = builtin.definition_and_resource_files()
    await db.pool.execute(
        "INSERT INTO workflows (id,key,title,executor,definition_repo_id,definition_path,"
        "current_commit_sha,version_label,definition) VALUES ($1,$2,'QA','codex.procedure',"
        "'registry/workflows','qa.json',$3,'1.3.0',$4::jsonb)",
        builtin.id,
        builtin.key,
        "a" * 40,
        json.dumps(definition),
    )
    service = integrations()
    sealed = prepare(CARD, workflow=WORKFLOW, integrations=service)
    args = dict(
        project_id=project.id,
        workflow_id=builtin.id,
        input_payload={"product_url": "https://example.test"},
        start_idempotency_key="card-run",
    )
    run, created = await db.create_run(**args, payment_card=sealed)
    assert created
    assert await load(db, service, run_id=run.id) == CARD
    assert await load(db, service, run_id=uuid4()) is None
    row = await db.pool.fetchrow("SELECT * FROM run_payment_cards WHERE run_id=$1", run.id)
    assert CARD["number"].encode() not in row["ciphertext"]
    assert "payment_card" not in run.input
    replay, created = await db.create_run(**args, payment_card=sealed)
    assert replay.id == run.id and not created
    changed = prepare({**CARD, "name": "Different Tester"}, workflow=WORKFLOW, integrations=service)
    with pytest.raises(WorkflowInputError, match="cannot change"):
        await db.create_run(**args, payment_card=changed)
    clean, _ = await db.create_run(**{**args, "start_idempotency_key": "separate-run"})
    assert await load(db, service, run_id=clean.id) is None
    with pytest.raises(WorkflowInputError, match="cannot change"):
        await db.create_run(
            **{**args, "start_idempotency_key": "separate-run"}, payment_card=sealed
        )
    # The database boundary covers every terminal path, including failure and stop.
    for status in ["succeeded", "failed", "stopped", "superseded"]:
        next_run, _ = await db.create_run(
            **{**args, "start_idempotency_key": status},
            payment_card=sealed,
        )
        await db.pool.execute("UPDATE workflow_runs SET status=$2 WHERE id=$1", next_run.id, status)
        assert await load(db, service, run_id=next_run.id) is None
