"""One run-bound procedure stop, shared by HTTP, MCP and the technical-fix alias."""

import asyncio

from temporalio.service import RPCError, RPCStatusCode


async def stop_procedure(*, runtime, run_id, actor, workflow_key=None):
    run = await runtime.database.get_run(run_id)
    if run is None or not await runtime.database.has_project_access(
        project_id=run.project_id, clerk_user_id=actor
    ):
        raise LookupError("run not found")
    if run.review_source_run_id is not None and run.status.value in {"failed", "stopped"}:
        from tin_lite.domain import SideEffectConflictError
        from tin_lite.workflow_review_store import ReviewConflict
        from tin_lite.workflow_reviews import WorkflowReviews

        reviews = WorkflowReviews(runtime=runtime, settings=None)
        view = await reviews.view(run.id, actor)
        try:
            stopped = await reviews.cancel_failed_revision(
                run_id=run.id, actor=actor, token=view["review_token"]
            )
        except ReviewConflict as exc:
            raise SideEffectConflictError(str(exc)) from exc
        return {
            "id": str(stopped.id),
            "status": stopped.status.value,
            "notice": "Revision stopped. The previous copy remains readable.",
        }
    stopped = await runtime.database.stop_codex_procedure(
        run_id=run.id,
        project_id=run.project_id,
        actor=actor,
        expected_generation=run.generation,
        workflow_key=workflow_key,
    )
    if stopped.review_source_run_id is not None:
        from tin_lite.workflow_reviews import WorkflowReviews

        reviews = WorkflowReviews(runtime=runtime, settings=None)
        view = await reviews.view(stopped.id, actor)
        await reviews.cancel_failed_revision(
            run_id=stopped.id, actor=actor, token=view["review_token"]
        )

    async def cancel():
        try:
            async with asyncio.timeout(15):
                await runtime.temporal.get_workflow_handle(stopped.temporal_workflow_id).cancel()
        except RPCError as exc:
            # A stop may win before Temporal starts. Activity admission still rejects it.
            if exc.status != RPCStatusCode.NOT_FOUND:
                raise

    async def cleanup():
        if stopped.sandbox_id is not None:
            async with asyncio.timeout(15):
                await runtime.sandboxes.kill(stopped.sandbox_id)

    # A Temporal outage must not prevent killing the paid compute, or vice versa.
    # Repeating Stop retries both without another product event. Never return upstream errors.
    outcomes = await asyncio.gather(cancel(), cleanup(), return_exceptions=True)
    pending = [isinstance(outcome, BaseException) for outcome in outcomes]
    notice = (
        "The run is stopped. Cleanup is pending; retry Stop to confirm cleanup."
        if any(pending)
        else "Stopped. Saved output is retained."
    )
    if stopped.executor != "workflow.code":
        notice += " Already accepted provider work may still incur costs."
    return {
        "id": str(stopped.id),
        "status": stopped.status.value,
        "cancellation_pending": pending[0],
        "cleanup_pending": pending[1],
        "notice": notice,
    }
