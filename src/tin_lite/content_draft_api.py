"""Read-only preparation; actual starts use the ordinary authenticated run endpoint."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from tin_lite.auth import AuthContext, require_user
from tin_lite.content_draft_sources import ContentDraftSources

router = APIRouter(prefix="/api/projects/{project_id}/content-drafts")
USER = Depends(require_user)


@router.get("/sources")
async def sources(
    project_id: UUID,
    request: Request,
    program_id: UUID | None = None,
    user: AuthContext = USER,
):
    runtime = request.app.state.runtime
    if not await runtime.database.has_project_access(
        project_id=project_id, clerk_user_id=user.clerk_user_id
    ):
        raise HTTPException(status_code=404, detail="project not found")
    try:
        return await ContentDraftSources(
            database=runtime.database, storage=runtime.storage
        ).discover(project_id=project_id, program_id=program_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Content program not found.") from exc
    except (ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=409,
            detail="The content plan is unavailable or invalid. Refresh its Files entry.",
        ) from exc
