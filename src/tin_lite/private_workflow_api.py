"""HTTP transport for the same private-package lifecycle exposed over MCP."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from tin_lite.auth import AuthContext, require_user
from tin_lite.domain import SideEffectConflictError
from tin_lite.private_workflows import (
    PackageActivation,
    PackageSelection,
    PrivateWorkflowArchive,
    PrivateWorkflowError,
    PrivateWorkflows,
    authoring_guide,
)
from tin_lite.workflow_qualification_service import (
    CandidateSelection,
    EvaluationStart,
    QualificationSelection,
    WorkflowQualification,
    qualification_result,
)

router = APIRouter(prefix="/api/projects/{project_id}/workflow-packages")
USER = Depends(require_user)


def qualifier(request):
    runtime = request.app.state.runtime
    return WorkflowQualification(
        database=runtime.database, storage=runtime.storage, settings=request.app.state.settings
    )


@router.post("/candidate")
async def candidate(
    project_id: UUID, payload: CandidateSelection, request: Request, user: AuthContext = USER
):
    return await result(
        qualification_result(
            qualifier(request).candidate(
                project_id=project_id, actor=user.clerk_user_id, run_id=payload.run_id
            )
        )
    )


@router.post("/qualify")
async def qualify(
    project_id: UUID, payload: QualificationSelection, request: Request, user: AuthContext = USER
):
    return await result(
        qualification_result(
            qualifier(request).qualify(
                project_id=project_id, actor=user.clerk_user_id, selection=payload
            )
        )
    )


@router.post("/evaluate")
async def evaluate(
    project_id: UUID, payload: EvaluationStart, request: Request, user: AuthContext = USER
):
    """Explicit live evaluation; normal project admission, execution and billing apply."""
    return await result(
        qualification_result(
            qualifier(request).start_case(
                runtime=request.app.state.runtime,
                project_id=project_id,
                actor=user.clerk_user_id,
                client_id=user.client_id,
                selection=payload,
            )
        )
    )


def service(request):
    runtime = request.app.state.runtime
    return PrivateWorkflows(
        database=runtime.database, storage=runtime.storage, settings=request.app.state.settings
    )


async def result(call):
    try:
        return await call
    except LookupError as exc:
        raise HTTPException(
            status_code=404, detail="project or private workflow not found"
        ) from exc
    except PrivateWorkflowError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.diagnostic()) from exc
    except SideEffectConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "request_conflict", "message": "This request ID is already in use."},
        ) from exc


@router.get("/guide")
async def guide(project_id: UUID, request: Request, user: AuthContext = USER):
    await result(service(request).project(project_id, user.clerk_user_id))
    return authoring_guide(settings=request.app.state.settings, project_id=project_id)


@router.post("/validate")
async def validate(
    project_id: UUID, payload: PackageSelection, request: Request, user: AuthContext = USER
):
    return await result(
        service(request).validate(
            project_id=project_id, actor=user.clerk_user_id, selection=payload
        )
    )


@router.post("/activate")
async def activate(
    project_id: UUID, payload: PackageActivation, request: Request, user: AuthContext = USER
):
    return await result(
        service(request).activate(
            project_id=project_id,
            actor=user.clerk_user_id,
            client_id=user.client_id,
            selection=payload,
        )
    )


@router.post("/{workflow_id}/archive")
async def archive(
    project_id: UUID,
    workflow_id: UUID,
    payload: PrivateWorkflowArchive,
    request: Request,
    user: AuthContext = USER,
):
    return await result(
        service(request).archive(
            project_id=project_id,
            workflow_id=workflow_id,
            actor=user.clerk_user_id,
            client_id=user.client_id,
            selection=payload,
        )
    )
