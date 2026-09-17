"""Self-hosted execution keeps observations but has no customer payment policy."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from test_billing import billed as billed
from test_mcp_auth import FakeOAuthAuth
from test_private_workflows import ACTOR, activate, app, fixture
from test_procedure_publication import publication_db as publication_db

from tin_lite.billing import BillingService, configure_billing
from tin_lite.billing_recovery import billing_reconciliation_loop
from tin_lite.mcp_server import create_mcp_app
from tin_lite.run_service import start_workflow_run
from tin_lite.settings import Settings


def test_billing_is_an_explicit_deployment_setting():
    assert Settings.model_fields["billing_enabled"].default is False
    assert Settings.model_fields["stripe_secret_key"].default is None
    assert Settings.model_fields["stripe_webhook_secret"].default is None


async def test_disabled_billing_has_no_reconciliation():
    database = SimpleNamespace(billing=None, pool=SimpleNamespace(fetch=AsyncMock()))
    await billing_reconciliation_loop(SimpleNamespace(database=database), SimpleNamespace())
    database.pool.fetch.assert_not_called()


async def test_self_hosted_mode_keeps_native_usage_observations(publication_db):
    from test_model_service import fixture as model_fixture
    from test_model_service import invoke, receipts

    db = publication_db
    await configure_billing(db, SimpleNamespace())
    run, router, calls = await model_fixture(db)
    try:
        await invoke(db, run, router)
        [(status, record)] = await receipts(db)
        assert status == "completed" and record["usage"]["total_tokens"] == 16
        assert len(calls) == 1
        assert await db.pool.fetchval("SELECT count(*) FROM billing_operations") == 0
    finally:
        await router.close()


async def test_disabled_billing_does_not_publish_payment_tools():
    settings = SimpleNamespace(
        switchboard_public_url="https://tin.test", clerk_frontend_api_url="https://clerk.test"
    )
    server, _ = create_mcp_app(settings=settings, auth=FakeOAuthAuth(), runtime=lambda: None)
    names = {tool.name for tool in await server.list_tools()}
    assert {"start_workflow", "start_project_workflow", "get_run_usage"} <= names
    assert (
        not {
            "quote_workflow_run",
            "get_project_spending",
            "create_billing_checkout",
            "refund_billing_payment",
            "get_run_charge",
            "enroll_billing_test",
        }
        & names
    )


async def test_self_hosted_run_needs_no_quote_or_stripe(publication_db):
    f = await fixture(publication_db)
    await activate(f)
    await configure_billing(f.db, f.settings)
    assert f.db.billing is None
    workflow = next(
        w
        for w in await f.db.list_workflows(project_id=f.project.id)
        if w.key == "custom.research_digest"
    )
    run = await start_workflow_run(
        runtime=f.runtime,
        settings=f.settings,
        workflow=workflow,
        project_id=f.project.id,
        started_by_clerk_user_id=ACTOR,
        input_payload={"brief": "Summarize project evidence"},
        start_idempotency_key="self-hosted-no-billing",
    )
    assert await f.db.get_run(run.id)
    assert await f.db.pool.fetchval("SELECT count(*) FROM billing_run_budgets") == 0
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(f)), base_url="https://tin.test"
    ) as client:
        for path in (
            f"/api/projects/{f.project.id}/billing",
            f"/api/workflows/runs/{run.id}/charge",
        ):
            assert (await client.get(path)).status_code == 404
        assert (await client.post("/webhooks/stripe/tin-lite")).status_code == 404


async def test_existing_billed_database_cannot_silently_become_unbilled(billed):
    f = billed
    f.settings.billing_enabled = False
    with pytest.raises(RuntimeError, match="TIN_LITE_BILLING_ENABLED"):
        await configure_billing(f.db, f.settings)
    f.settings.billing_enabled = True
    f.settings.billing_test_enabled = False
    await configure_billing(f.db, f.settings)
    assert isinstance(f.db.billing, BillingService)
