"""One bounded native extraction; reuse the existing saved-output publication contract."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from uuid import UUID

from temporalio import activity
from temporalio.exceptions import ApplicationError

from tin_lite import style_capture as style
from tin_lite.model_providers import MessageRole, ModelMessage, ModelRequest
from tin_lite.model_usage import model_usage_scope
from tin_lite.publication import OutputCheckpoint, OutputConflictError, PublicationPendingError
from tin_lite.writing_style import STYLE_PATH


class StyleCaptureActivities:
    def __init__(self, *, database, storage, router):
        self.db, self.storage, self.router = database, storage, router

    async def active(self, run_id, *, conn=None):
        run = await self.db.get_run(UUID(str(run_id)), conn=conn)
        if not run or run.executor != style.KEY or run.status.value not in {"pending", "running"}:
            raise ValueError("Style capture is no longer active.")
        return run

    @activity.defn(name="style_prepare")
    async def prepare(self, run_id: str):
        try:
            run = await self.active(run_id)
            await self.db.mark_run_running(run.id)
            key = f"{run.id}:style_context"
            async with self.db.effect_lock(key, style.KEY) as (conn, saved):
                if saved and saved.status == "completed":
                    return
                project = await self.db.get_project(run.project_id, conn=conn)
                packet, revision = await style.read_sources(
                    self.storage, project, run.input["source_path"]
                )
                existing = await self.storage.read_output_destination(
                    repo_id=project.state_repo_id, revision=revision, path=STYLE_PATH
                )
                guide = existing[1].decode("utf-8") if existing else ""
                if len(guide.encode()) > style.MAX_GUIDE_BYTES:
                    raise ValueError("The existing writing guide is too large; shorten it first.")
                definition = json.loads(
                    await self.storage.read_canonical_artifact(
                        repo_id="registry/workflows",
                        commit_sha=run.definition_commit_sha,
                        path=f"workflows/{style.KEY}.json",
                    )
                )
                if definition.get("model_route") != style.route_definition() or (
                    definition.get("style_policy") != style.POLICY
                ):
                    raise ValueError("This worker does not serve the selected style contract.")
                async with conn.transaction():
                    await self.db.start_effect(conn, execution_key=key, operation=style.KEY)
                    updated = await conn.fetchval(
                        """UPDATE workflow_runs SET expected_head_sha=$2
                           WHERE id=$1 AND executor='style.capture' AND status='running'
                             AND (expected_head_sha IS NULL OR expected_head_sha=$2)
                           RETURNING id""",
                        run.id,
                        revision,
                    )
                    if not updated:
                        raise ValueError("Style capture's source snapshot changed.")
                    await self.db.complete_effect(
                        conn,
                        execution_key=key,
                        result={
                            "packet": packet.model_dump(),
                            "revision": revision,
                            "existing_guide": guide,
                            "instructions": definition["style_instructions"],
                            "schema": definition["style_schema"],
                        },
                    )
            await self.progress(run.id, "read", 1, "Selected writing samples are ready")
        except ValueError:
            raise ApplicationError(
                "Style sources are invalid or unavailable. Check the selected sample packet.",
                non_retryable=True,
            ) from None

    async def progress(self, run_id, step, current, summary):
        await self.db.project_run_progress(
            run_id=run_id, mode="steps", step=step, current=current, total=3, summary=summary
        )

    @activity.defn(name="style_extract")
    async def extract(self, run_id: str):
        run = await self.active(run_id)
        key = f"{run.id}:style_model"
        context = (await self.db.get_effect(f"{run.id}:style_context")).result
        await self.progress(run.id, "extract", 1, "Extracting voice and editorial preferences")
        async with self.db.effect_lock(key, style.KEY) as (conn, saved):
            if saved and saved.status == "completed":
                return
            if saved:
                raise ApplicationError(
                    "The previous model request is unconfirmed; no replacement was purchased.",
                    non_retryable=True,
                )
            await self.active(run.id, conn=conn)
            await self.db.start_effect(conn, execution_key=key, operation=style.KEY)
            try:
                with model_usage_scope(run_id=run.id, step="style:capture", conn=conn):
                    async with asyncio.timeout(180):
                        result = await self.router.generate(
                            style.ROUTE.key,
                            ModelRequest(
                                system=context["instructions"],
                                messages=(
                                    ModelMessage(
                                        role=MessageRole.USER,
                                        content=json.dumps(
                                            {
                                                "samples": context["packet"],
                                                "existing_guide": context["existing_guide"],
                                                "direction": (run.input or {}).get("direction", ""),
                                            }
                                        ),
                                    ),
                                ),
                                output_schema=context["schema"],
                                output_schema_name="writing_style",
                                max_output_tokens=style.POLICY["max_output_tokens"],
                            ),
                        )
                # Receipt precedes semantic validation; a retry cannot buy a repair call.
                await self.db.complete_effect(
                    conn,
                    execution_key=key,
                    result={
                        "data": result.parsed,
                        "usage": asdict(result.usage),
                        "model": result.model,
                        "request_id": result.request_id,
                    },
                )
            except Exception:
                raise ApplicationError(
                    "The style model request could not be confirmed; no replacement was purchased.",
                    non_retryable=True,
                ) from None

    @activity.defn(name="style_publish")
    async def publish(self, run_id: str):
        run = await self.db.get_run(UUID(run_id))
        if run and run.executor == style.KEY and run.status.value == "succeeded":
            return
        run = await self.active(run_id)
        project = await self.db.get_project(run.project_id)
        context = (await self.db.get_effect(f"{run.id}:style_context")).result
        model = (await self.db.get_effect(f"{run.id}:style_model")).result
        try:
            content = style.render_guide(
                model["data"],
                style.SourcePacket.model_validate(context["packet"]),
                source_path=run.input["source_path"],
                revision=context["revision"],
                direction=(run.input or {}).get("direction", ""),
                existing_preferences=style.explicit_preferences(context["existing_guide"]),
            )
        except (ValueError, TypeError):
            raise ApplicationError(
                "The extracted guide is invalid. The current guide is unchanged.",
                non_retryable=True,
            ) from None
        await self.progress(run.id, "save", 2, "Saving the editable writing guide")
        checkpoint_key = f"{run.id}:style_artifact_persist"
        async with self.db.effect_lock(checkpoint_key, style.KEY) as (conn, saved):
            if saved and saved.status == "completed":
                checkpoint = OutputCheckpoint.load(saved.result["checkpoint"], run=run)
                checkpoint.validate_content(content)
            else:
                await self.db.start_effect(conn, execution_key=checkpoint_key, operation=style.KEY)
                await self.active(run.id, conn=conn)
                revision = await self.storage.stage_native_output(
                    repo_id=project.state_repo_id,
                    branch=project.canonical_branch,
                    run_id=str(run.id),
                    generation=run.generation,
                    path=STYLE_PATH,
                    content=content,
                )
                checkpoint = OutputCheckpoint.create(
                    run=run,
                    revision=revision,
                    path=STYLE_PATH,
                    media_type="text/markdown",
                    content=content,
                )
                await self.db.complete_effect(
                    conn, execution_key=checkpoint_key, result={"checkpoint": checkpoint.to_dict()}
                )
        key = f"{run.id}:style_publish"
        async with self.db.effect_lock(key, style.KEY) as (conn, saved):
            if saved and saved.status == "completed":
                return
            intent = (saved.result or {}).get("publication") if saved else None
            await self.db.start_effect(conn, execution_key=key, operation=style.KEY)
            await self.db.retain_procedure_output(
                conn, run_id=run.id, checkpoint=checkpoint.to_dict(), reason="publication_pending"
            )

            async def save_intent(value):
                await self.db.save_publication_intent(conn, execution_key=key, intent=value)

            async def validate():
                await self.active(run.id, conn=conn)

            try:
                async with self.db.project_state_lock(conn, project.id):
                    sha, _ = await self.storage.publish_procedure_output(
                        repo_id=project.state_repo_id,
                        branch=project.canonical_branch,
                        checkpoint=checkpoint,
                        content=content,
                        execution_key=key,
                        workflow_key=style.KEY,
                        intent=intent,
                        legacy_attempt=False,
                        save_intent=save_intent,
                        validate_lease=validate,
                    )
                    async with conn.transaction():
                        await self.db._complete_readonly_report_projection(
                            conn,
                            execution_key=key,
                            run_id=run.id,
                            canonical_commit_sha=sha,
                            artifact_path=STYLE_PATH,
                            artifact_ref=f"code.storage://{project.state_repo_id}@{sha}/{STYLE_PATH}",
                            summary="Writing style captured. Future drafts can use this guide.",
                            workflow_key=style.KEY,
                        )
                        await conn.execute(
                            "UPDATE workflow_runs SET retained_output=NULL WHERE id=$1", run.id
                        )
            except (OutputConflictError, PublicationPendingError) as exc:
                conflict = isinstance(exc, OutputConflictError)
                await self.db.retain_procedure_output(
                    conn,
                    run_id=run.id,
                    checkpoint=checkpoint.to_dict(),
                    reason="output_conflict" if conflict else "reconciliation_pending",
                )
                if conflict:
                    raise ApplicationError(
                        "The writing guide changed during capture. "
                        "Your guide was kept; compare the saved result.",
                        non_retryable=True,
                    ) from None
                raise

    @activity.defn(name="style_failure")
    async def failure(self, run_id: str):
        run = await self.db.get_run(UUID(run_id))
        if run and run.executor == style.KEY:
            await self.db.project_failure(
                run_id=run.id,
                error_message=(
                    "Style capture could not confirm completion. "
                    "Check the current guide and any saved result before trying again."
                ),
            )
