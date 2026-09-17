"""Create-only report publication for fixed organic-system/technical-fix outcomes."""

from uuid import UUID

from tin_lite.organic_audit import digest
from tin_lite.organic_audit_publication import publish_artifacts


async def publish_report_file(
    *,
    database,
    storage,
    run_id,
    workflow_key,
    prefix,
    path,
    content,
):
    """Publish one report file under the run's effect receipt; the run's status is untouched."""
    run_id = UUID(str(run_id))
    run = await database.get_run(run_id)
    project = await database.get_project(run.project_id)

    async def active(conn):
        current = await database.get_run(run_id, conn=conn)
        if current.status.value not in {"pending", "running", "succeeded"}:
            raise ValueError("The run is no longer active.")

    key = f"{prefix}:{run_id}:publish"
    async with database.effect_lock(key, workflow_key) as (conn, receipt):
        if receipt and receipt.status == "completed":
            if receipt.result["content_sha256"] != digest(content.decode()):
                raise ValueError("The saved report differs from this outcome.")
            revision = receipt.result["canonical_commit_sha"]
        else:
            await database.start_effect(conn, execution_key=key, operation=workflow_key)

            async def save_intent(intent):
                await database.save_publication_intent(conn, execution_key=key, intent=intent)

            async with database.project_state_lock(conn, project.id):
                revision = await publish_artifacts(
                    storage=storage,
                    repo_id=project.state_repo_id,
                    branch=project.canonical_branch,
                    documents={path: content},
                    paths={"RESULT.md": path},
                    limits={"RESULT.md": 100_000},
                    message=f"{workflow_key} {run_id} [{key}]",
                    intent=(receipt.result or {}).get("publication") if receipt else None,
                    save_intent=save_intent,
                    validate_active=lambda: active(conn),
                )
            await database.complete_effect(
                conn,
                execution_key=key,
                result={
                    "canonical_commit_sha": revision,
                    "artifact_path": path,
                    "content_sha256": digest(content.decode()),
                },
            )
    return revision


async def publish_run_report(
    *,
    database,
    storage,
    run_id,
    workflow_key,
    prefix,
    path,
    content,
    summary,
    failed=False,
):
    revision = await publish_report_file(
        database=database,
        storage=storage,
        run_id=run_id,
        workflow_key=workflow_key,
        prefix=prefix,
        path=path,
        content=content,
    )
    run_id = UUID(str(run_id))
    project = await database.get_project((await database.get_run(run_id)).project_id)
    key = f"{prefix}:{run_id}:projection"
    async with database.effect_lock(key, workflow_key) as (conn, receipt):
        if receipt and receipt.status == "completed":
            return
        await database.start_effect(conn, execution_key=key, operation=workflow_key)
        await database._complete_readonly_report_projection(
            conn,
            execution_key=key,
            run_id=run_id,
            canonical_commit_sha=revision,
            artifact_path=path,
            artifact_ref=f"code.storage://{project.state_repo_id}@{revision}/{path}",
            summary=summary,
            workflow_key=workflow_key,
            final_status="failed" if failed else "succeeded",
        )
