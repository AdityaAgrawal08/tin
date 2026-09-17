"""Thin HTTP and MCP-compatible request contracts for prepaid billing."""

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from tin_lite.auth import AuthContext, require_user
from tin_lite.billing import BillingService
from tin_lite.billing_contracts import BillingError, ProjectSpendingPolicy
from tin_lite.billing_payments import StripePayments


def private_response(response: Response):
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(dependencies=[Depends(private_response)])
USER = Depends(require_user)


class QuoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workflow_id: UUID | None = None
    project_workflow_id: UUID | None = None
    inputs: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def one_source(self):
        if bool(self.workflow_id) == bool(self.project_workflow_id):
            raise ValueError("Choose one workflow or saved configuration.")
        if self.project_workflow_id and self.inputs:
            raise ValueError("Saved workflow quotes use its saved inputs.")
        return self


class TopupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    amount_cents: int = Field(strict=True, ge=1000, le=100000)


def service(request):
    return BillingService(
        database=request.app.state.runtime.database, settings=request.app.state.settings
    )


def payments(request):
    return StripePayments(billing=service(request), settings=request.app.state.settings)


async def result(call):
    try:
        return await call
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="billing resource not found") from exc
    except BillingError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.diagnostic()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid billing request.") from exc


@router.get("/api/projects/{project_id}/billing")
async def overview(project_id: UUID, request: Request, user: AuthContext = USER):
    return await result(service(request).overview(project_id, user.clerk_user_id))


@router.post("/api/projects/{project_id}/billing/estimate")
async def estimate(
    project_id: UUID, payload: QuoteRequest, request: Request, user: AuthContext = USER
):
    return await result(
        service(request).quote(
            runtime=request.app.state.runtime,
            project_id=project_id,
            actor=user.clerk_user_id,
            preview_only=True,
            **payload.model_dump(),
        )
    )


@router.post("/api/projects/{project_id}/billing/quotes")
async def quote(
    project_id: UUID, payload: QuoteRequest, request: Request, user: AuthContext = USER
):
    return await result(
        service(request).quote(
            runtime=request.app.state.runtime,
            project_id=project_id,
            actor=user.clerk_user_id,
            **payload.model_dump(),
        )
    )


@router.put("/api/projects/{project_id}/billing/limits")
async def policy(
    project_id: UUID, payload: ProjectSpendingPolicy, request: Request, user: AuthContext = USER
):
    return await result(service(request).update_policy(project_id, user.clerk_user_id, payload))


@router.get("/api/workflows/runs/{run_id}/charge")
async def run_charge(run_id: UUID, request: Request, user: AuthContext = USER):
    return await result(service(request).run_charge(run_id, user.clerk_user_id))


@router.post("/api/workspaces/{workspace_id}/billing/test-enrollment")
async def enroll(workspace_id: UUID, request: Request, user: AuthContext = USER):
    return await result(service(request).enroll_test(workspace_id, user.clerk_user_id))


@router.get("/api/workspaces/{workspace_id}/billing/payments")
async def payment_list(workspace_id: UUID, request: Request, user: AuthContext = USER):
    return await result(payments(request).list_payments(workspace_id, user.clerk_user_id))


@router.get("/api/billing/payments/{payment_id}/return")
async def checkout_return(payment_id: UUID, request: Request, user: AuthContext = USER):
    return await result(payments(request).checkout_return(payment_id, user.clerk_user_id))


@router.post("/api/workspaces/{workspace_id}/billing/checkout")
async def checkout(
    workspace_id: UUID, payload: TopupRequest, request: Request, user: AuthContext = USER
):
    return await result(
        payments(request).checkout(
            workspace_id=workspace_id,
            actor=user.clerk_user_id,
            **payload.model_dump(),
        )
    )


@router.post("/webhooks/stripe/tin-lite")
async def webhook(request: Request, stripe_signature: str = Header(default="")):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 512_000:
            raise HTTPException(status_code=413, detail="Webhook body too large.")
    return await result(payments(request).webhook(bytes(body), stripe_signature))
