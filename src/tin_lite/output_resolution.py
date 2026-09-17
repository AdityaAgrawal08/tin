"""Member-driven, whole-file resolution of a retained procedure output.

Policy decides *whether* to request this action; this service always enforces the
same exact-version and retry contract. No workflow, sandbox, or model is resumed.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from tin_lite.domain import RunStatus, SideEffectConflictError
from tin_lite.project_files import safe_project_file_path
from tin_lite.publication import (
    RETAINED_OUTPUT_EXECUTORS,
    OutputCheckpoint,
    OutputConflictError,
    PublicationPendingError,
    StaleOutputComparisonError,
    output_checkpoint_key,
)

MAX_COMPARISON_BYTES = 200_000
MAX_COMPARISON_LINES = 10_000
MAX_STARTING_BYTES = 100_000
MAX_STARTING_LINES = 5_000


class OutputResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    action: Literal["keep_current", "use_saved"]
    expected_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    saved_revision: str = Field(pattern=r"^[0-9a-f]{40}$")


class OutputResolutionError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class OutputResolutionService:
    def __init__(self, *, database, storage):
        self._db = database
        self._storage = storage

    async def _context(self, run_id: UUID, *, conn=None):
        run = await self._db.get_run(run_id, conn=conn)
        if run is None:
            raise LookupError("run not found")
        if (
            run.executor not in RETAINED_OUTPUT_EXECUTORS
            or run.retained_output is None
            or run.retained_output.get("reason") != "output_conflict"
            or run.canonical_commit_sha is not None
            or run.status not in {RunStatus.FAILED, RunStatus.STOPPED}
            or run.lease_active
        ):
            raise OutputResolutionError(
                "not_resolvable", "This run has no settled output conflict."
            )
        checkpoint = OutputCheckpoint.load(run.retained_output, run=run)
        if not safe_project_file_path(checkpoint.artifact_path):
            raise OutputResolutionError("unsafe_path", "This saved path cannot be applied.")
        persisted = await self._db.get_effect(output_checkpoint_key(run), conn=conn)
        if (
            persisted is None
            or persisted.status != "completed"
            or persisted.result is None
            or persisted.result.get("checkpoint") != checkpoint.to_dict()
        ):
            raise OutputResolutionError(
                "invalid_checkpoint", "The saved output cannot be verified."
            )
        project = await self._db.get_project(run.project_id, conn=conn)
        if project is None:
            raise LookupError("project not found")
        return run, project, checkpoint

    async def _comparison(self, run, project, checkpoint, *, revision: str):
        async with asyncio.timeout(60):
            saved = await self._storage.read_procedure_checkpoint(
                repo_id=project.state_repo_id,
                revision=checkpoint.ephemeral_commit_sha,
                path=checkpoint.artifact_path,
                binary=checkpoint.media_type == "video/mp4",
            )
            checkpoint.validate_content(saved)
            reason = None
            try:
                entry = await self._storage.read_output_destination(
                    repo_id=project.state_repo_id,
                    revision=revision,
                    path=checkpoint.artifact_path,
                )
            except OutputConflictError:
                entry = None
                reason = "unsafe_destination"
            current = entry[1] if entry is not None else b""
            for item in checkpoint.companions:
                try:
                    original = await self._storage.read_output_destination(
                        repo_id=project.state_repo_id,
                        revision=checkpoint.source_base_sha,
                        path=item.artifact_path,
                    )
                    companion = await self._storage.read_output_destination(
                        repo_id=project.state_repo_id, revision=revision, path=item.artifact_path
                    )
                    if original != companion:
                        reason = "companion_changed"
                except OutputConflictError:
                    reason = "companion_changed"
            try:
                current_text = current.decode("utf-8")
            except UnicodeDecodeError:
                current_text = None
                reason = "non_text_destination"
            try:
                saved_text = saved.decode("utf-8")
            except UnicodeDecodeError:
                saved_text = None
                reason = "non_text_output"
            if reason is None and (
                len(current) + len(saved) > MAX_COMPARISON_BYTES
                or current.count(b"\n") + saved.count(b"\n") + 2 > MAX_COMPARISON_LINES
            ):
                reason = "comparison_limit"
            complete = reason is None
            return {
                "run_id": str(run.id),
                "project_id": str(project.id),
                "path": checkpoint.artifact_path,
                "media_type": checkpoint.media_type,
                "complete": complete,
                "blocked_reason": reason,
                "identical": entry is not None and current == saved if complete else None,
                "current": {
                    "revision": revision,
                    "presence": "unavailable"
                    if reason == "unsafe_destination"
                    else "file"
                    if entry is not None
                    else "missing",
                    "mode": entry[0] if entry is not None else None,
                    "byte_count": len(current) if reason != "unsafe_destination" else None,
                    "sha256": hashlib.sha256(current).hexdigest() if entry is not None else None,
                    "content": current_text if complete and entry is not None else None,
                },
                "saved": {
                    "revision": checkpoint.ephemeral_commit_sha,
                    "byte_count": len(saved),
                    "sha256": checkpoint.sha256,
                    "content": saved_text if complete else None,
                },
                "resolution": run.output_resolution,
                "allowed_actions": []
                if run.output_resolution
                else (["keep_current", "use_saved"] if complete else ["keep_current"]),
            }, saved

    async def compare(self, *, run_id: UUID) -> dict:
        run, project, checkpoint = await self._context(run_id)
        repo = await self._storage.get_repo(project.state_repo_id)
        revision = await self._storage.head_sha(repo, project.canonical_branch)
        if not isinstance(revision, str) or len(revision) != 40:
            raise PublicationPendingError("project revision is unavailable")
        comparison, _ = await self._comparison(run, project, checkpoint, revision=revision)
        comparison["starting"] = await self._starting_snapshot(
            project, checkpoint, complete=comparison["complete"]
        )
        return comparison

    async def _starting_snapshot(self, project, checkpoint, *, complete: bool) -> dict:
        # Optional context, never an input to authorization or whole-file application.
        result = {
            "revision": checkpoint.source_base_sha,
            "available": False,
            "presence": "unavailable",
            "content": None,
            "blocked_reason": "comparison_incomplete",
        }
        if not complete:
            return result
        try:
            async with asyncio.timeout(10):
                entry = await self._storage.read_output_destination(
                    repo_id=project.state_repo_id,
                    revision=checkpoint.source_base_sha,
                    path=checkpoint.artifact_path,
                )
                content = entry[1] if entry is not None else b""
                if (
                    len(content) > MAX_STARTING_BYTES
                    or content.count(b"\n") + 1 > MAX_STARTING_LINES
                ):
                    return {**result, "blocked_reason": "starting_limit"}
                text = content.decode("utf-8")
                return {
                    **result,
                    "available": True,
                    "presence": "file" if entry is not None else "missing",
                    "content": text if entry is not None else None,
                    "blocked_reason": None,
                }
        except Exception:
            # No exception text: storage errors may contain credential-bearing URLs.
            return {**result, "blocked_reason": "starting_unavailable"}

    async def status(
        self, *, run_id: UUID, actor_clerk_user_id: str, client_id: str | None
    ) -> dict:
        """Postgres-only recovery context, including when storage is unavailable.

        A read never retries an effect. Only the original authenticated actor/client
        receives a retry request, reconstructed from its durable intent, not the browser.
        """
        run, _, checkpoint = await self._context(run_id)
        resolution = run.output_resolution
        retry_request = None
        if resolution and resolution.get("state") == "applying":
            receipt = await self._db.get_effect(
                f"{run.id}:output_resolution:{resolution['request_id']}"
            )
            facts = (receipt.result or {}).get("request", {}) if receipt else {}
            if (
                facts.get("actor_clerk_user_id") == actor_clerk_user_id
                and facts.get("client_id") == client_id
                and facts.get("checkpoint") == checkpoint.to_dict()
            ):
                retry_request = OutputResolutionRequest.model_validate(
                    {field: facts[field] for field in OutputResolutionRequest.model_fields}
                ).model_dump(mode="json")
        return {
            "run_id": str(run.id),
            "project_id": str(run.project_id),
            "path": checkpoint.artifact_path,
            "resolution": resolution,
            "retry_request": retry_request,
        }

    @staticmethod
    def _outcome(value: dict, *, replayed: bool) -> dict:
        if value["state"] == "stale":
            raise OutputResolutionError(
                "stale_comparison",
                "The project changed. Compare again and use a new request ID.",
            )
        return {**value, "replayed": replayed}

    async def resolve(
        self,
        *,
        run_id: UUID,
        request: OutputResolutionRequest,
        actor_clerk_user_id: str,
        client_id: str | None,
    ) -> dict:
        # The adapter must authorize project membership before invoking this service.
        # Attribution is authenticated context, never an action-body field.
        async with self._db.effect_lock(f"{run_id}:output_resolution", "output_resolution") as (
            conn,
            _,
        ):
            run, project, checkpoint = await self._context(run_id, conn=conn)
            if request.saved_revision != checkpoint.ephemeral_commit_sha:
                raise OutputResolutionError(
                    "wrong_saved_version", "Compare the saved version again."
                )
            facts = {
                **request.model_dump(mode="json"),
                "run_id": str(run.id),
                "project_id": str(project.id),
                "checkpoint": checkpoint.to_dict(),
                "actor_clerk_user_id": actor_clerk_user_id,
                "client_id": client_id,
                "basis": "member_request",
            }
            key = f"{run.id}:output_resolution:{request.request_id}"
            existing = await self._db.get_effect(key, conn=conn)
            if existing is not None:
                if (
                    existing.operation != "output_resolution"
                    or (existing.result or {}).get("request") != facts
                ):
                    raise SideEffectConflictError("request ID belongs to another resolution")
                if existing.status == "completed":
                    return self._outcome(existing.result["outcome"], replayed=True)
            if run.output_resolution is not None:
                if run.output_resolution["request_id"] != str(request.request_id):
                    raise OutputResolutionError(
                        "resolution_exists", "A saved-output decision already exists."
                    )
                if existing is None:
                    raise OutputResolutionError(
                        "resolution_unavailable", "The decision receipt is unavailable."
                    )

            projection = {
                "run_id": str(run.id),
                "request_id": str(request.request_id),
                "action": request.action,
                "path": checkpoint.artifact_path,
                "expected_revision": request.expected_revision,
                "saved_revision": request.saved_revision,
                "state": "applying",
                "revision": None,
                "changed": False,
            }
            intent = (existing.result or {}).get("publication") if existing else None
            async with self._db.project_state_lock(conn, project.id):
                # Once a write may have happened, reconcile first. Current file contents
                # or an expired comparison cannot hide the earlier successful effect.
                if intent is not None:
                    content = await self._storage.read_procedure_checkpoint(
                        repo_id=project.state_repo_id,
                        revision=checkpoint.ephemeral_commit_sha,
                        path=checkpoint.artifact_path,
                        binary=checkpoint.media_type == "video/mp4",
                    )
                    checkpoint.validate_content(content)
                else:
                    repo = await self._storage.get_repo(project.state_repo_id)
                    head = await self._storage.head_sha(repo, project.canonical_branch)
                    if head != request.expected_revision:
                        async with conn.transaction():
                            if existing is None:
                                await self._db.begin_output_resolution(
                                    conn,
                                    run_id=run.id,
                                    execution_key=key,
                                    request=facts,
                                    checkpoint=checkpoint.to_dict(),
                                    resolution=projection,
                                )
                            await self._db.complete_output_resolution(
                                conn,
                                run_id=run.id,
                                execution_key=key,
                                request=facts,
                                checkpoint=checkpoint.to_dict(),
                                outcome={**projection, "state": "stale"},
                            )
                        raise OutputResolutionError(
                            "stale_comparison", "The project changed. Compare again."
                        )
                    comparison, content = await self._comparison(
                        run,
                        project,
                        checkpoint,
                        revision=request.expected_revision,
                    )
                    if request.action == "use_saved" and not comparison["complete"]:
                        raise OutputResolutionError(
                            "comparison_blocked", "A complete safe comparison is required."
                        )
                if existing is None:
                    await self._db.begin_output_resolution(
                        conn,
                        run_id=run.id,
                        execution_key=key,
                        request=facts,
                        checkpoint=checkpoint.to_dict(),
                        resolution=projection,
                    )

                async def save_intent(value):
                    await self._db.save_publication_intent(conn, execution_key=key, intent=value)

                try:
                    if request.action == "keep_current":
                        revision, changed = request.expected_revision, False
                    else:
                        revision, changed = await self._storage.apply_saved_output(
                            repo_id=project.state_repo_id,
                            branch=project.canonical_branch,
                            checkpoint=checkpoint,
                            content=content,
                            expected_revision=request.expected_revision,
                            execution_key=key,
                            intent=intent,
                            save_intent=save_intent,
                        )
                    outcome = {
                        **projection,
                        "state": "applied" if request.action == "use_saved" else "kept",
                        "revision": revision,
                        "changed": changed,
                    }
                    await self._db.complete_output_resolution(
                        conn,
                        run_id=run.id,
                        execution_key=key,
                        request=facts,
                        checkpoint=checkpoint.to_dict(),
                        outcome=outcome,
                    )
                    return self._outcome(outcome, replayed=False)
                except StaleOutputComparisonError as exc:
                    await self._db.complete_output_resolution(
                        conn,
                        run_id=run.id,
                        execution_key=key,
                        request=facts,
                        checkpoint=checkpoint.to_dict(),
                        outcome={**projection, "state": "stale"},
                    )
                    raise OutputResolutionError(
                        "stale_comparison", "The project changed. Compare again."
                    ) from exc
                except Exception as exc:
                    await self._db.fail_effect(
                        conn, execution_key=key, error_message=type(exc).__name__
                    )
                    raise OutputResolutionError(
                        "resolution_pending",
                        "The outcome is unconfirmed. Retry the exact same request.",
                        status_code=503,
                    ) from exc
