"""Welcome grants use the existing ledger, without opting users into paid execution."""

import asyncio
from uuid import UUID, uuid4

import httpx
import pytest
from test_billing import billed as billed
from test_billing import finish, fund, quote, start
from test_private_workflows import ACTOR, app, mcp, structured
from test_procedure_publication import publication_db as publication_db

from tin_lite.billing_contracts import NANOS_PER_DOLLAR, BillingError
from tin_lite.onboarding import billing_restrictions


async def enable(f):
    f.settings.billing_welcome_credits_enabled = True
    await f.db.record_tin_user(ACTOR)


async def test_one_grant_under_concurrent_signins_and_project_reads(billed):
    f = billed
    f.settings.billing_welcome_credits_enabled = True
    await asyncio.gather(*(f.db.record_tin_user(ACTOR) for _ in range(8)))
    await f.db.list_projects_for_user(ACTOR)
    assert await f.db.pool.fetchval("SELECT count(*) FROM billing_welcome_grants") == 1
    assert await f.db.pool.fetchval("SELECT count(*) FROM billing_ledger") == 1
    overview = await f.billing.overview(f.project.id, ACTOR)
    assert overview["available_usd"] == "10.00"
    assert overview["transactions"][0]["kind"] == "welcome_credit"
    assert overview["run_billing_enabled"] is True
    assert await f.payments.list_payments(f.project.workspace_id, ACTOR) == []
    assert f.calls == []


@pytest.mark.parametrize("legacy", [False, True])
async def test_new_wallet_does_not_enroll_or_block_onboarding(billed, legacy):
    f = billed
    await f.db.pool.execute(
        "DELETE FROM billing_project_policies WHERE project_id=$1", f.project.id
    )
    await f.db.pool.execute(
        "DELETE FROM billing_accounts WHERE workspace_id=$1", f.project.workspace_id
    )
    if legacy:
        await f.db.pool.execute(
            "UPDATE workspaces SET created_by_clerk_user_id=NULL WHERE id=$1",
            f.project.workspace_id,
        )
    await enable(f)
    overview = await f.billing.overview(f.project.id, ACTOR)
    assert overview["available_usd"] == "10.00"
    assert overview["run_billing_enabled"] is False
    assert await quote(f) == {"enabled": False, "mode": "disabled"}
    assert (
        await billing_restrictions(database=f.db, project_id=f.project.id, workflows=[f.workflow])
        == {}
    )
    async with f.db.pool.acquire() as conn:
        # No run row/quote or model tariff is necessary on the unenrolled admission path.
        await f.billing.admit(
            conn, run={"project_id": f.project.id}, definition={"executor": "growth.onboarding"}
        )
    if legacy:
        assert (
            await f.db.pool.fetchval(
                "SELECT created_by_clerk_user_id FROM workspaces WHERE id=$1",
                f.project.workspace_id,
            )
            is None
        )  # No invented creator or membership.
    await f.billing.enroll_test(f.project.workspace_id, ACTOR)
    assert (await f.billing.overview(f.project.id, ACTOR))["run_billing_enabled"] is True
    assert (await quote(f))["enabled"] is True
    assert await f.db.pool.fetchval("SELECT count(*) FROM billing_welcome_grants") == 1


async def test_projectless_user_gets_grant_after_provisioning_not_a_new_workspace(billed):
    f, actor = billed, "user_NewWelcome"
    f.settings.billing_welcome_credits_enabled = True
    await f.db.record_tin_user(actor)
    assert await f.billing.grant_welcome_credit(actor) is False
    workspace_id, project_id = uuid4(), uuid4()
    await f.db.bootstrap_personal_project(
        workspace_id=workspace_id,
        workspace_name="New workspace",
        project_id=project_id,
        name="New project",
        state_repo_id=f"projects/{project_id}",
        clerk_user_id=actor,
        reuse_existing=True,
    )
    projects = await f.db.list_projects_for_user(actor)
    assert [p.id for p in projects] == [project_id]
    assert (await f.billing.overview(project_id, actor))["available_usd"] == "10.00"
    # The next project and sign-in do not earn a second grant.
    another = await f.db.bootstrap_personal_project(
        workspace_id=uuid4(),
        workspace_name="Second workspace",
        project_id=uuid4(),
        name="Unused",
        state_repo_id="unused",
        clerk_user_id=actor,
        reuse_existing=False,
    )
    await f.db.record_tin_user(actor)
    assert (await f.billing.overview(another.id, actor))["enabled"] is False
    assert (
        await f.db.pool.fetchval(
            "SELECT count(*) FROM billing_welcome_grants WHERE clerk_user_id=$1", actor
        )
        == 1
    )


async def test_invited_users_pool_credits_without_receiving_billing_authority(billed):
    f, actor = billed, "user_InvitedWelcome"
    await enable(f)
    await f.db.record_tin_user(actor)  # no membership yet
    await f.db.pool.execute(
        "INSERT INTO project_memberships(project_id,clerk_user_id) VALUES($1,$2)",
        f.project.id,
        actor,
    )
    assert len(await f.db.list_projects_for_user(actor)) == 1
    assert (await f.billing.overview(f.project.id, ACTOR))["available_usd"] == "20.00"
    assert (await f.billing.overview(f.project.id, actor))["is_admin"] is False
    assert (
        await f.db.pool.fetchval(
            "SELECT count(*) FROM workspace_memberships WHERE clerk_user_id=$1", actor
        )
        == 0
    )
    with pytest.raises(LookupError):
        await f.payments.list_payments(f.project.workspace_id, actor)


async def test_shared_identity_directory_is_not_imported_and_disabled_mode_grants_nothing(billed):
    f = billed
    await f.db.record_tin_user(ACTOR)
    assert await f.db.pool.fetchval("SELECT count(*) FROM billing_welcome_grants") == 0
    f.settings.billing_welcome_credits_enabled = True
    assert await f.billing.grant_welcome_credit("user_NotSignedIntoTin") is False
    assert await f.db.pool.fetchval("SELECT count(*) FROM billing_welcome_grants") == 0


async def test_grant_spent_before_cash_and_cannot_be_refunded(billed):
    f = billed
    await enable(f)
    payment, _ = await fund(f, 1000)
    run = await start(f, await quote(f))
    async with f.db.pool.acquire() as conn:
        await f.billing.begin_operation(
            conn,
            run_id=run.id,
            operation_id="welcome-spend",
            kind="isolated_codex",
            maximum=NANOS_PER_DOLLAR,
        )
        await f.billing.observe_operation(
            conn, operation_id="welcome-spend", nanos=480_000_000, observation={}
        )
    await finish(f, run)
    assert await f.billing.settle(run.id) == 500_000_000
    assert await f.billing.settle(run.id) == 500_000_000
    account = await f.db.pool.fetchrow(
        "SELECT * FROM billing_accounts WHERE workspace_id=$1", f.project.workspace_id
    )
    assert account["welcome_remaining_nanos"] == 9_500_000_000
    assert account["balance_nanos"] == 19_500_000_000
    assert (
        await f.db.pool.fetchval(
            "SELECT consumed_cents FROM billing_payments WHERE id=$1", UUID(payment["id"])
        )
        == 0
    )
    assert (await f.payments.list_payments(f.project.workspace_id, ACTOR))[0][
        "refundable_usd"
    ] == "10.00"
    with pytest.raises(BillingError, match="not available"):
        await f.payments.request_refund(UUID(payment["id"]), ACTOR, uuid4(), 1001)


async def test_backfill_does_not_make_previously_spent_cash_refundable(billed):
    f = billed
    payment, _ = await fund(f, 1000)
    run = await start(f, await quote(f))
    async with f.db.pool.acquire() as conn:
        await f.billing.begin_operation(
            conn,
            run_id=run.id,
            operation_id="cash-spend",
            kind="isolated_codex",
            maximum=NANOS_PER_DOLLAR,
        )
        await f.billing.observe_operation(
            conn, operation_id="cash-spend", nanos=480_000_000, observation={}
        )
    await finish(f, run)
    await f.billing.settle(run.id)
    await enable(f)
    assert (await f.payments.list_payments(f.project.workspace_id, ACTOR))[0][
        "refundable_usd"
    ] == "9.50"


async def test_http_and_mcp_reuse_same_welcome_grant(billed, monkeypatch):
    f = billed
    await enable(f)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(f)), base_url="https://tin.test"
    ) as client:
        response = await client.get(f"/api/projects/{f.project.id}/billing")
        retired_refund = await client.post(f"/api/billing/payments/{uuid4()}/refunds", json={})
        assert retired_refund.status_code == 404
    assert response.status_code == 200
    assert response.json()["available_usd"] == "10.00"
    result = structured(
        await mcp(f, monkeypatch).call_tool(
            "get_project_spending", {"project_id": str(f.project.id)}
        )
    )
    assert result["available_usd"] == "10.00"
    assert await f.db.pool.fetchval("SELECT count(*) FROM billing_welcome_grants") == 1
