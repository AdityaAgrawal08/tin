"""The audit's shared HTTP/MCP stop boundary, independent from Luna."""

from uuid import UUID


async def stop_organic_audit(*, runtime, run_id: UUID, clerk_user_id: str):
    run = await runtime.database.get_run(run_id)
    if run is None or not await runtime.database.has_project_access(
        project_id=run.project_id, clerk_user_id=clerk_user_id
    ):
        raise LookupError("run not found")
    if run.executor != "organic.audit":
        raise ValueError("This control stops an organic audit only.")
    stopped = await runtime.database.stop_organic_audit(
        run_id=run_id, project_id=run.project_id, actor=clerk_user_id
    )
    # The projection fences subsequent paid work even if the signal needs retry.
    await runtime.temporal.get_workflow_handle(run.temporal_workflow_id).signal("stop")
    return stopped
