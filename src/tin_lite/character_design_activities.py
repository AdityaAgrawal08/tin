"""Temporal activities for `creative.character`: prepare, design, publish, review."""

from __future__ import annotations

import json
import time
from uuid import UUID

from temporalio import activity
from temporalio.exceptions import ApplicationError

from tin_lite.character_design import (
    KEY,
    MAX_MEMORY_CHARS,
    ROUTE_KEY,
    CharacterDesign,
    CharacterDesigner,
    CharacterDesignError,
    DesignBrief,
    fetch_product_page,
    model_route_definition,
)
from tin_lite.model_usage import model_usage_scope
from tin_lite.studio_contracts import validate_character_svg

CHARACTER_PATH_PREFIX = "characters/"
_PROGRESS_TOTAL = 3


def character_path(slug: str) -> str:
    return f"{CHARACTER_PATH_PREFIX}{slug}.svg"


class CharacterDesignActivities:
    def __init__(self, *, database, storage, settings, designer: CharacterDesigner | None) -> None:
        self.db, self.storage, self.settings, self.designer = database, storage, settings, designer

    async def _run(self, run_id: str):
        run = await self.db.get_run(UUID(run_id))
        if run is None or run.executor != KEY:
            raise ValueError("this run is not a character design")
        return run

    async def _pinned_route(self, run) -> str:
        definition = json.loads(
            await self.storage.read_canonical_artifact(
                repo_id="registry/workflows",
                commit_sha=run.definition_commit_sha,
                path=f"workflows/{KEY}.json",
            )
        )
        if definition.get("model_route") != model_route_definition():
            raise ValueError("this worker does not serve the pinned character model route")
        return ROUTE_KEY

    @activity.defn(name="character_design")
    async def character_design(self, run_id: str) -> None:
        try:
            await self.design(run_id)
        except CharacterDesignError as exc:
            # Tin-owned messages only; never model text or SDK errors.
            raise ApplicationError(str(exc)[:500], non_retryable=True) from None

    async def design(self, run_id: str) -> None:
        if self.designer is None:
            raise CharacterDesignError("the character designer is not configured")
        run = await self._run(run_id)
        commit_key = f"{run.id}:character:commit"
        if (committed := await self.db.get_effect(commit_key)) and committed.status == "completed":
            return
        project = await self.db.get_project(run.project_id)
        if project is None:
            raise CharacterDesignError("project not found")
        route_key = await self._pinned_route(run)
        inputs = run.input or {}
        slug = str(inputs.get("slug", ""))
        path = character_path(slug)
        await self.db.mark_run_running(run.id)
        await self.db.project_run_progress(
            run_id=run.id,
            mode="steps",
            step="prepare",
            current=0,
            total=_PROGRESS_TOTAL,
            summary="Reading the product page and project memory",
        )
        started = time.monotonic()
        context = await self._context(run, project, inputs)
        await self.db.project_run_progress(
            run_id=run.id,
            mode="steps",
            step="design",
            current=1,
            total=_PROGRESS_TOTAL,
            summary="Asking the model for the character",
        )
        design = await self._design(run, context, route_key)
        await self.db.project_run_progress(
            run_id=run.id,
            mode="steps",
            step="publish",
            current=2,
            total=_PROGRESS_TOTAL,
            summary="Saving the character to project Files",
        )
        async with self.db.effect_lock(commit_key, "character_commit") as (conn, existing):
            if existing is not None and existing.status == "completed":
                return
            await self.db.start_effect(conn, execution_key=commit_key, operation="character_commit")
            try:
                validate_character_svg(design.svg)
                async with self.db.project_state_lock(conn, project.id):
                    sha, changed = await self.storage.publish_state_document(
                        repo_id=project.state_repo_id,
                        branch=project.canonical_branch,
                        path=path,
                        content=design.svg,
                        workflow_key=KEY,
                        execution_key=commit_key,
                        run_id=str(run.id),
                    )
                timings = dict(design.timings_ms)
                timings["total"] = int((time.monotonic() - started) * 1000)
                await self.db.add_activity(
                    run_id=run.id,
                    event_type="character_designed",
                    details={
                        "path": path,
                        "changed": changed,
                        "model": design.model,
                        "timings_ms": timings,
                        "repairs": design.repairs,
                        "refined": design.refined,
                        "usage": design.usage,
                        "page": context.get("page_url"),
                    },
                    dedupe_key=f"{commit_key}:designed",
                )
                await self.db.complete_effect(
                    conn,
                    execution_key=commit_key,
                    result={
                        "canonical_commit_sha": sha,
                        "artifact_path": path,
                        "changed": changed,
                        "concept": design.concept,
                        "timings_ms": timings,
                        "warnings": list(design.warnings),
                    },
                )
            except Exception as exc:
                await self.db.fail_effect(
                    conn, execution_key=commit_key, error_message=type(exc).__name__
                )
                raise

    async def _context(self, run, project, inputs: dict) -> dict:
        key = f"{run.id}:character:context"
        async with self.db.effect_lock(key, "character_context") as (conn, existing):
            if existing is not None and existing.status == "completed" and existing.result:
                return existing.result
            await self.db.start_effect(conn, execution_key=key, operation="character_context")
            memory = ""
            if project.memory_commit_sha and project.memory_index_path:
                raw = await self.storage.read_canonical_artifact(
                    repo_id=project.state_repo_id,
                    commit_sha=project.memory_commit_sha,
                    path=project.memory_index_path,
                )
                memory = raw.decode("utf-8", errors="replace")[:MAX_MEMORY_CHARS]
            page = None
            page_error = ""
            url = str(inputs.get("product_url") or "").strip()
            if url:
                try:
                    page = (await fetch_product_page(url)).definition()
                except CharacterDesignError as exc:
                    page_error = str(exc)
            result = {
                "project_name": project.name,
                "memory": memory,
                "page": page,
                "page_url": url,
                "page_error": page_error,
            }
            await self.db.complete_effect(conn, execution_key=key, result=result)
            return result

    async def _design(self, run, context: dict, route_key: str) -> CharacterDesign:
        key = f"{run.id}:character:model"
        async with self.db.effect_lock(key, "character_model") as (conn, existing):
            if existing is not None and existing.status == "completed" and existing.result:
                return CharacterDesign.from_receipt(existing.result)
            if existing is not None and existing.status == "started":
                raise CharacterDesignError(
                    "the previous model request is unconfirmed; no replacement was purchased"
                )
            await self.db.start_effect(conn, execution_key=key, operation="character_model")
            inputs = run.input or {}
            brief = DesignBrief(
                project_name=str(context.get("project_name") or ""),
                slug=str(inputs.get("slug", "")),
                brief=str(inputs.get("brief") or ""),
                notes=str(inputs.get("notes") or ""),
                memory=str(context.get("memory") or ""),
                page=_page_from_context(context.get("page")),
            )
            try:
                with model_usage_scope(run_id=run.id, step="character", conn=conn):
                    design = await self.designer.design(brief, route_key=route_key)
            except CharacterDesignError as exc:
                await self.db.fail_effect(conn, execution_key=key, error_message=str(exc)[:500])
                raise
            except Exception as exc:
                await self.db.fail_effect(conn, execution_key=key, error_message=type(exc).__name__)
                raise CharacterDesignError("the character model request did not complete") from exc
            await self.db.complete_effect(conn, execution_key=key, result=design.receipt())
            return design

    @activity.defn(name="character_review")
    async def character_review(self, run_id: str) -> bool:
        run = await self._run(run_id)
        committed = await self.db.get_effect(f"{run.id}:character:commit")
        if committed is None or committed.status != "completed" or committed.result is None:
            raise RuntimeError("the character commit step has not completed")
        project = await self.db.get_project(run.project_id)
        sha = str(committed.result["canonical_commit_sha"])
        path = str(committed.result["artifact_path"])
        content = await self.storage.read_canonical_artifact(
            repo_id=project.state_repo_id, commit_sha=sha, path=path
        )
        validate_character_svg(content)
        return await self.db.request_human_review(
            run_id=run.id,
            canonical_commit_sha=sha,
            artifact_ref=f"code.storage://{project.state_repo_id}@{sha}/{path}",
            artifact_path=path,
            summary="Your character is ready for your review.",
        )

    @activity.defn(name="character_approval")
    async def character_approval(self, run_id: str) -> None:
        await self.db.record_human_review(run_id=UUID(run_id), decision="approved")

    @activity.defn(name="character_project")
    async def character_project(self, run_id: str) -> None:
        run = await self._run(run_id)
        key = f"{run.id}:character:projection"
        async with self.db.effect_lock(key, "character_projection") as (conn, existing):
            if existing is not None and existing.status == "completed":
                return
            await self.db.start_effect(conn, execution_key=key, operation="character_projection")
            committed = await self.db.get_effect(f"{run.id}:character:commit")
            if committed is None or committed.status != "completed" or committed.result is None:
                raise RuntimeError("the character commit step has not completed")
            project = await self.db.get_project(run.project_id)
            sha = str(committed.result["canonical_commit_sha"])
            path = str(committed.result["artifact_path"])
            artifact_ref = f"code.storage://{project.state_repo_id}@{sha}/{path}"
            await self.db.project_success(
                run_id=run.id,
                canonical_commit_sha=sha,
                artifact_ref=artifact_ref,
                artifact_path=path,
            )
            await self.db.add_activity(
                run_id=run.id,
                event_type="character_ready",
                details={"artifact_ref": artifact_ref},
                summary="Brand character is ready.",
                audience="product",
                dedupe_key=f"{key}:ready",
            )
            await self.db.complete_effect(
                conn, execution_key=key, result={"artifact_ref": artifact_ref}
            )

    @activity.defn(name="character_failure")
    async def character_failure(self, payload: dict[str, str]) -> None:
        await self.db.project_failure(
            run_id=UUID(payload["run_id"]),
            error_message=payload.get("reason", "the character design did not finish"),
        )


def _page_from_context(value):
    from tin_lite.character_design import ProductPage

    if not isinstance(value, dict):
        return None
    try:
        return ProductPage(
            url=str(value["url"]),
            final_url=str(value["final_url"]),
            title=str(value["title"]),
            description=str(value["description"]),
            headings=tuple(str(item) for item in value["headings"]),
            actions=tuple(str(item) for item in value["actions"]),
            text=str(value["text"]),
            colors=tuple(str(item) for item in value["colors"]),
            theme_color=str(value["theme_color"]),
        )
    except (KeyError, TypeError):
        return None
