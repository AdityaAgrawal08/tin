"""Transactional review arbitration. Callers hold the project row before the run row."""

import hashlib
import json
from uuid import UUID


class ReviewConflict(ValueError):
    """The exact version being reviewed is no longer actionable."""


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def unpack(row):
    result = dict(row)
    for key in ("artifact", "reference_files"):
        if isinstance(result.get(key), str):
            result[key] = json.loads(result[key])
    return result


async def guard_transition(conn, *, project_id, command):
    """Runs in the same transaction as ordinary admission, including its budget reserve."""
    member = await conn.fetchval(
        "SELECT true FROM project_memberships WHERE project_id=$1 AND clerk_user_id=$2",
        project_id,
        command["actor_clerk_user_id"],
    )
    if not member:
        raise LookupError("Review not found.")
    accepted = await conn.fetchrow(
        "SELECT * FROM workflow_review_commands WHERE source_run_id=$1",
        command["source_run_id"],
    )
    if accepted:
        if (
            accepted["project_id"] == project_id
            and accepted["request_id"] == command["request_id"]
            and accepted["request_digest"] == command["request_digest"]
            and accepted["actor_clerk_user_id"] == command["actor_clerk_user_id"]
        ):
            return
        raise ReviewConflict("This version already has a review decision. Open the current review.")
    source = await conn.fetchrow(
        "SELECT * FROM workflow_runs WHERE id=$1 AND project_id=$2 FOR UPDATE",
        command["source_run_id"],
        project_id,
    )
    if not source:
        raise LookupError("Review not found.")
    if source["review_decision"] is not None:
        raise ReviewConflict("This draft is already approved. Delivery cannot be recalled here.")
    permitted = source["status"] == "needs_input"
    if command["action"] == "cancel":
        permitted = (
            source["status"] in {"failed", "stopped"} and source["review_source_run_id"] is not None
        )
    if command["action"] == "revise":
        permitted |= source["status"] == "succeeded" and command["artifact"].get(
            "assessment", False
        )
        permitted |= source["status"] == "failed" and source["review_source_run_id"] is not None
    if not permitted:
        raise ReviewConflict("This version is not available for review. Open the current review.")
    if source["status"] not in {"failed", "stopped"} and (
        source["canonical_commit_sha"] != command["artifact"]["revision"]
        or source["artifact_path"] != command["artifact"]["path"]
    ):
        raise ReviewConflict("The reviewed artifact changed. Read it again before deciding.")
    # A program amendment uses the same program lock as admission. Do not mix old
    # feedback with a newly selected brief or race an already-held batch amendment.
    selection = command.get("draft_selection")
    if selection:
        revision = await conn.fetchval(
            "SELECT plan_revision FROM content_programs WHERE project_workflow_id=$1 "
            "AND project_id=$2",
            UUID(selection["program_id"]),
            project_id,
        )
        if revision != command["program_revision"]:
            raise ReviewConflict(
                "The content program changed while submitting. Read its brief again."
            )
        held = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM content_plan_revisions WHERE project_workflow_id=$1 "
            "AND project_id=$2 AND status IN ('pending','applying') AND batch_ids ? $3)",
            UUID(selection["program_id"]),
            project_id,
            selection["batch_id"],
        )
        if held:
            raise ReviewConflict("Finish the pending amendment to this batch before revising.")


async def insert_command(conn, command, *, successor_id=None):
    await conn.execute(
        """INSERT INTO workflow_review_commands
           (id, project_id, request_id, actor_clerk_user_id, source_run_id, root_run_id,
            artifact_run_id, coordinator_run_id, action, request_digest, review_token,
            artifact, feedback, reference_files, successor_run_id)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb,$13,$14::jsonb,$15)""",
        command["id"],
        command["project_id"],
        command["request_id"],
        command["actor_clerk_user_id"],
        command["source_run_id"],
        command["root_run_id"],
        command["artifact_run_id"],
        command["coordinator_run_id"],
        command["action"],
        command["request_digest"],
        command["review_token"],
        json.dumps(command["artifact"]),
        command.get("feedback", ""),
        json.dumps(command.get("reference_files", [])),
        successor_id,
    )


async def accept_revision(conn, *, command, successor):
    source = await conn.fetchrow(
        "SELECT * FROM workflow_runs WHERE id=$1", command["source_run_id"]
    )
    if (
        source["project_id"] != successor["project_id"]
        or source["workflow_id"] != successor["workflow_id"]
    ):
        raise ReviewConflict("A revision must belong to the same project and workflow.")
    await insert_command(conn, command, successor_id=successor["id"])
    row = await conn.fetchrow(
        """UPDATE workflow_runs SET review_root_run_id=$2, review_source_run_id=$3,
           review_version=$4, progress_summary='Revising from your feedback'
           WHERE id=$1 RETURNING *""",
        successor["id"],
        command["root_run_id"],
        source["id"],
        source["review_version"] + 1,
    )
    await conn.execute(
        """UPDATE workflow_runs SET status='superseded', finished_at=COALESCE(finished_at,now()),
           lease_active=false, lease_released_at=COALESCE(lease_released_at,now()),
           progress_summary='A revision was requested. The previous copy remains readable.'
           WHERE id=$1""",
        source["id"],
    )
    await conn.execute("DELETE FROM broker_grants WHERE run_id=$1", source["id"])
    await conn.execute(
        """UPDATE run_decisions SET status='dismissed', applied_at=now(),
           applied_by_clerk_user_id=$2, response=$3::jsonb WHERE run_id=$1 AND status='pending'""",
        source["id"],
        command["actor_clerk_user_id"],
        json.dumps({"action": "revise", "successor_run_id": str(successor["id"])}),
    )
    await conn.execute(
        """INSERT INTO activity_events
           (project_id,run_id,event_type,details,summary,audience,dedupe_key)
           VALUES ($1,$2,'workflow_revision_requested',$3::jsonb,$4,'product',$5)
           ON CONFLICT (dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING""",
        source["project_id"],
        successor["id"],
        json.dumps({"kind": "your_edits", "source_run_id": str(source["id"])}),
        f"Changes requested. Preparing version {row['review_version']}.",
        f"{command['id']}:revision",
    )
    return row


async def accept_cancellation(database, command):
    async with database.pool.acquire() as conn, conn.transaction():
        await conn.execute("SELECT id FROM projects WHERE id=$1 FOR UPDATE", command["project_id"])
        await guard_transition(conn, project_id=command["project_id"], command=command)
        if await conn.fetchval(
            "SELECT id FROM workflow_review_commands WHERE source_run_id=$1",
            command["source_run_id"],
        ):
            return
        await insert_command(conn, command)
        await conn.execute(
            "UPDATE workflow_runs SET status='stopped', finished_at=COALESCE(finished_at,now()), "
            "progress_summary='Revision stopped. The previous copy remains readable.' WHERE id=$1",
            command["source_run_id"],
        )
        await conn.execute(
            """INSERT INTO activity_events
               (project_id,run_id,event_type,details,summary,audience,dedupe_key)
               VALUES ($1,$2,'workflow_revision_stopped','{"kind":"your_edits"}'::jsonb,
                       'Revision stopped. Previous copy retained.','product',$3)
               ON CONFLICT (dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING""",
            command["project_id"],
            command["source_run_id"],
            f"{command['id']}:stopped",
        )


async def accept_approval(database, command):
    async with database.pool.acquire() as conn, conn.transaction():
        await conn.execute("SELECT id FROM projects WHERE id=$1 FOR UPDATE", command["project_id"])
        await guard_transition(conn, project_id=command["project_id"], command=command)
        exists = await conn.fetchval(
            "SELECT id FROM workflow_review_commands WHERE source_run_id=$1",
            command["source_run_id"],
        )
        if exists:
            return
        await insert_command(conn, command)
        await conn.execute(
            """UPDATE workflow_runs SET review_decision='approved', reviewed_at=now(),
               reviewed_by_clerk_user_id=$2, status='running',
               progress_summary='Approved. Finishing the run.' WHERE id=$1""",
            command["source_run_id"],
            command["actor_clerk_user_id"],
        )
        await conn.execute(
            """UPDATE run_decisions SET status='applied', applied_at=now(),
               applied_by_clerk_user_id=$2, response='{"action":"approved"}'::jsonb
               WHERE run_id=$1 AND status='pending'""",
            command["source_run_id"],
            command["actor_clerk_user_id"],
        )
