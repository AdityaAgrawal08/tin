from __future__ import annotations

from uuid import UUID, uuid4

from tin_lite.code_storage import CodeStorage
from tin_lite.db import Database
from tin_lite.email_outreach import (
    build_campaign_revision_plan,
    campaign_revision_path,
    render_email_template,
)

MAX_EMAIL_BODY_BYTES = 20_000


async def request_email_campaign_revision(
    *,
    database: Database,
    storage: CodeStorage,
    run_id: UUID,
    request_id: UUID,
    follow_up_body: str,
    clerk_user_id: str,
) -> dict[str, object]:
    revised_body = follow_up_body.strip()
    if len(revised_body.encode("utf-8")) > MAX_EMAIL_BODY_BYTES:
        raise ValueError("revised follow-up exceeds 20000 UTF-8 bytes")
    render_email_template(revised_body, name="Recipient")

    candidate_revision_id = uuid4()
    provisional_path = campaign_revision_path(run_id, candidate_revision_id)
    revision = await database.begin_email_campaign_revision(
        revision_id=candidate_revision_id,
        run_id=run_id,
        request_id=request_id,
        follow_up_body=revised_body,
        review_path=provisional_path,
        clerk_user_id=clerk_user_id,
    )
    revision_id = revision["id"]
    assert isinstance(revision_id, UUID)
    if revision["status"] != "pending":
        return revision

    review_path = str(revision["review_path"])
    project = await database.get_project(revision["project_id"])
    if project is None:
        raise LookupError("project not found")
    pending_count = int(revision["pending_recipient_count"])
    plan = build_campaign_revision_plan(
        run_id=run_id,
        revision_id=revision_id,
        revision_number=int(revision["revision_number"]),
        previous_follow_up_body=str(revision["previous_follow_up_body"]),
        follow_up_body=revised_body,
        pending_recipient_count=pending_count,
    )
    execution_key = f"{run_id}:email_campaign_revision:{request_id}"
    operation = "email_campaign_revision_review"
    async with database.effect_lock(execution_key, operation) as (conn, existing):
        if existing is not None and existing.status == "completed":
            if existing.result is None:
                raise RuntimeError("email campaign revision receipt has no result")
            review_commit_sha = str(existing.result["review_commit_sha"])
        else:
            await database.start_effect(conn, execution_key=execution_key, operation=operation)
            try:
                async with database.project_state_lock(conn, project.id):
                    review_commit_sha, _ = await storage.publish_state_documents(
                        repo_id=project.state_repo_id,
                        branch=project.canonical_branch,
                        documents={review_path: plan},
                        workflow_key="outreach.email_campaign",
                        execution_key=execution_key,
                        run_id=str(run_id),
                    )
                await database.complete_effect(
                    conn,
                    execution_key=execution_key,
                    result={
                        "revision_id": str(revision_id),
                        "review_commit_sha": review_commit_sha,
                        "review_path": review_path,
                    },
                )
            except Exception as exc:
                await database.fail_effect(
                    conn,
                    execution_key=execution_key,
                    error_message=f"{type(exc).__name__}: revision review could not be published",
                )
                raise
    artifact_ref = f"code.storage://{project.state_repo_id}@{review_commit_sha}/{review_path}"
    return await database.finalize_email_campaign_revision(
        revision_id=revision_id,
        review_commit_sha=review_commit_sha,
        artifact_ref=artifact_ref,
        pending_recipient_count=pending_count,
    )
