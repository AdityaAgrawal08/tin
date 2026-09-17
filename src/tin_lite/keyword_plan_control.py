"""The keyword planner's shared, membership-gated HTTP/MCP stop boundary."""

from uuid import UUID

from tin_lite.keyword_plan import KEY


async def stop_keyword_plan(*, runtime, run_id: UUID, clerk_user_id: str):
    run = await runtime.database.get_run(run_id)
    if run is None or not await runtime.database.has_project_access(
        project_id=run.project_id, clerk_user_id=clerk_user_id
    ):
        raise LookupError("run not found")
    if run.executor != KEY:
        raise ValueError("This control stops a keyword plan only.")
    stopped = await runtime.database.stop_keyword_plan(
        run_id=run_id, project_id=run.project_id, actor=clerk_user_id
    )
    # Postgres fences new paid work even if delivery of the stop signal needs retry.
    await runtime.temporal.get_workflow_handle(run.temporal_workflow_id).signal("stop")
    return stopped
