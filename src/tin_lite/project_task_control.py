"""The one-off project task's shared, membership-gated HTTP/MCP control boundary.

A `project.task` run stops for its founder in three ways: it asks a question (`needs_input`),
it proposes file changes and waits for approval (`review`), or the founder paused it. The web
task page and the MCP server both answer, direct, and approve through this module so the two
surfaces never drift. Every read here is the Postgres projection; nothing reads Temporal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from tin_lite.domain import (
    PROJECT_TASK_WORKFLOW_NAME,
    ProjectTaskEntry,
    RunStatus,
    WorkflowRun,
)

TASK_MESSAGE_MAX_LENGTH = 8000
TASK_ENTRY_VIEW_LIMIT = 20
_FINISHED = {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.STOPPED}


class ProjectTaskConflictError(RuntimeError):
    """The task is not in a state that accepts this control."""


class ProjectTaskDeliveryError(RuntimeError):
    """Postgres recorded the control, but the task has not received it yet."""


@dataclass(frozen=True)
class ProjectTaskMessageResult:
    run: WorkflowRun
    entry: ProjectTaskEntry
    entries: list[ProjectTaskEntry]
    kind: str
    delivery: str


def is_project_task(run: WorkflowRun) -> bool:
    return run.executor == PROJECT_TASK_WORKFLOW_NAME


def task_message_kind(run: WorkflowRun) -> str:
    """A message answers a waiting question; anything else is direction."""
    return "answer" if run.task_phase == "needs_input" else "direction"


def project_task_allowed_actions(run: WorkflowRun) -> list[str]:
    """Controls an MCP client can exercise on this task right now.

    `answer` and `direct` both go through send_project_task_message; `approve` goes through
    approve_workflow_run. Pause and stop stay web-only until an MCP client needs them.
    """
    if run.status is RunStatus.NEEDS_INPUT:
        if run.task_phase == "needs_input":
            return ["answer"]
        if run.task_phase == "review":
            return ["approve", "direct"]
        return ["direct"]
    if run.status in {RunStatus.PENDING, RunStatus.RUNNING, RunStatus.PAUSED}:
        return ["direct"]
    return []


def project_task_entry_view(entry: ProjectTaskEntry) -> dict[str, Any]:
    return {
        "id": str(entry.id),
        "kind": entry.kind,
        "source": entry.source,
        "content": entry.content,
        "delivered_at": entry.delivered_at.isoformat() if entry.delivered_at else None,
        "created_at": entry.created_at.isoformat(),
    }


def project_task_view(
    run: WorkflowRun, entries: list[ProjectTaskEntry] | None = None
) -> dict[str, Any]:
    """The task facts a caller needs to decide what to do next.

    `question` is the exact text the task is waiting on when `phase` is `needs_input`.
    `entries`, when included, are the most recent transcript entries in order; the question
    the founder must answer is the latest `question` entry from `codex`.
    """
    changed_files = [
        {"path": item.get("path"), "state": item.get("state")}
        for item in (run.task_diff or {}).get("files", [])
        if isinstance(item, dict)
    ]
    view: dict[str, Any] = {
        "title": run.task_title,
        "phase": run.task_phase,
        "summary": run.task_summary,
        "question": run.task_question,
        "question_requested_at": (
            run.task_question_requested_at.isoformat()
            if run.task_question_requested_at is not None
            else None
        ),
        "turn_number": run.task_turn_number,
        "control": run.task_control,
        "result": run.task_result,
        "has_changes": run.task_has_changes,
        "changed_files": changed_files,
    }
    if entries is not None:
        view["entries_total"] = len(entries)
        view["entries"] = [
            project_task_entry_view(entry) for entry in entries[-TASK_ENTRY_VIEW_LIMIT:]
        ]
    return view


async def load_project_task(*, runtime, run_id: UUID, clerk_user_id: str) -> WorkflowRun:
    run = await runtime.database.get_run(run_id)
    if run is None or not await runtime.database.has_project_access(
        project_id=run.project_id, clerk_user_id=clerk_user_id
    ):
        raise LookupError("run not found")
    if not is_project_task(run):
        raise LookupError("task not found")
    return run


async def send_project_task_message(
    *,
    runtime,
    run_id: UUID,
    clerk_user_id: str,
    message: str,
    request_id: UUID | None = None,
) -> ProjectTaskMessageResult:
    """Answer a waiting question, resume a paused or reviewing task, or steer a running one.

    The entry is durable before delivery is attempted: a waiting task is resumed through its
    Temporal workflow and reads the entry at its next turn; a running task receives it on stdin
    when this switchboard holds the sandbox handle, and otherwise picks it up as an undelivered
    direction at the next turn.
    """
    normalized = message.strip()
    if not normalized:
        raise ValueError("enter a message")
    if len(normalized) > TASK_MESSAGE_MAX_LENGTH:
        raise ValueError(f"message must be at most {TASK_MESSAGE_MAX_LENGTH} characters")
    run = await load_project_task(runtime=runtime, run_id=run_id, clerk_user_id=clerk_user_id)
    if run.status in _FINISHED:
        raise ProjectTaskConflictError("task has finished")
    database = runtime.database
    waiting = run.status in {RunStatus.NEEDS_INPUT, RunStatus.PAUSED}
    kind = task_message_kind(run)
    if request_id is not None:
        # A replay after the first attempt resumed the task must keep the entry it saved,
        # even though the task has since moved on and a fresh message would be direction.
        prior = next(
            (
                entry
                for entry in await database.list_task_entries(run_id=run_id)
                if entry.request_id == request_id
            ),
            None,
        )
        if prior is not None:
            kind = prior.kind
    try:
        entry = await database.append_task_entry(
            run_id=run_id,
            request_id=request_id,
            kind=kind,
            source="founder",
            content=normalized,
            author_clerk_user_id=clerk_user_id,
        )
    except RuntimeError as exc:
        raise ProjectTaskConflictError(str(exc)) from exc
    try:
        if waiting:
            await database.clear_task_control(run_id=run_id)
            handle = runtime.temporal.get_workflow_handle(run.temporal_workflow_id)
            await handle.signal("resume")
            delivery = "resumed"
        else:
            delivered = await runtime.sandboxes.control_task(
                run_id=str(run_id),
                control={
                    "type": "steer",
                    "content": normalized,
                    "entry_id": str(entry.id),
                    "sequence": entry.id.int % 1_000_000_000,
                },
            )
            delivery = "steered" if delivered else "queued"
    except Exception as exc:
        raise ProjectTaskDeliveryError(
            "task direction was saved but could not be delivered yet"
        ) from exc
    refreshed = await database.get_run(run_id)
    assert refreshed is not None
    entries = await database.list_task_entries(run_id=run_id)
    return ProjectTaskMessageResult(
        run=refreshed, entry=entry, entries=entries, kind=kind, delivery=delivery
    )


async def approve_project_task(*, runtime, run_id: UUID, clerk_user_id: str) -> WorkflowRun:
    """Apply the reviewed changes; idempotent once approval is under way or done."""
    run = await load_project_task(runtime=runtime, run_id=run_id, clerk_user_id=clerk_user_id)
    if run.status is RunStatus.SUCCEEDED and run.review_decision == "approved":
        return run
    if run.status is RunStatus.RUNNING and run.task_phase == "applying":
        return run
    if run.status is not RunStatus.NEEDS_INPUT or run.task_phase != "review":
        raise ProjectTaskConflictError("task changes are not waiting for approval")
    try:
        handle = runtime.temporal.get_workflow_handle(run.temporal_workflow_id)
        await handle.signal("approve")
        return await runtime.database.begin_task_approval(
            run_id=run_id, clerk_user_id=clerk_user_id
        )
    except Exception as exc:
        raise ProjectTaskDeliveryError("task approval was not accepted") from exc
