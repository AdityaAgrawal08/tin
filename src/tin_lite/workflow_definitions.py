"""Resolve one complete selected contract without consulting moving metadata piecemeal."""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import replace
from typing import Any
from uuid import UUID

from tin_lite.domain import Workflow, WorkflowStatus
from tin_lite.workflow_inputs import WorkflowInputError, validate_input_schema
from tin_lite.workflow_packages import load_workflow_source


async def resolve_execution_contract(
    *,
    storage: Any,
    workflow: Workflow,
    project_id: UUID,
    revision: str | None = None,
    input_schema: dict[str, Any] | None = None,
) -> Workflow:
    """Return the selected definition as a Workflow; never mutate its catalog projection.

    The catalog's body is already an exact-commit projection and can serve that revision.
    Older selections must be loaded from immutable storage, not supplemented with today's
    policy. Source location and executor identity are stable after catalog publication.
    Authentication is owned by callers; project ownership and current availability are
    checked here before any source read and rechecked when the database creates the run.
    """
    if workflow.project_id not in (None, project_id):
        raise LookupError("workflow is not available to this project")
    if workflow.status != WorkflowStatus.ACTIVE:
        raise WorkflowInputError("workflow is not active")
    from tin_lite.workflows import registered_workflow_implementations

    if workflow.executor not in registered_workflow_implementations():
        raise WorkflowInputError("workflow executor is not installed")
    selected = revision if revision is not None else workflow.current_commit_sha
    if not isinstance(selected, str) or not re.fullmatch(r"[0-9a-f]{40}", selected):
        raise WorkflowInputError("workflow definition has no valid published revision")
    if selected == workflow.current_commit_sha:
        definition = deepcopy(workflow.definition)
    else:
        if storage is None:
            raise WorkflowInputError("selected workflow revision is unavailable")
        try:
            source = await load_workflow_source(
                storage=storage,
                repo_id=workflow.definition_repo_id,
                commit_sha=selected,
                definition_path=workflow.definition_path,
            )
            definition = source.definition
        except ValueError as exc:
            raise WorkflowInputError(
                "selected workflow definition is invalid or unavailable"
            ) from exc
    if not isinstance(definition, dict) or (
        definition.get("key") != workflow.key or definition.get("executor") != workflow.executor
    ):
        raise WorkflowInputError("selected definition does not match the workflow identity")
    schema = definition.get("input_schema")
    if not isinstance(schema, dict):
        raise WorkflowInputError("selected definition has no input schema")
    validate_input_schema(schema)
    if workflow.executor == "workflow.code":
        from tin_lite.workflow_code import validate_code_definition

        validate_code_definition(definition)
    if workflow.project_id is not None:
        from tin_lite.private_workflows import validate_private_definition

        validate_private_definition(definition)
    if input_schema is not None and schema != input_schema:
        raise WorkflowInputError("saved input schema does not match its selected definition")
    return replace(
        workflow,
        current_commit_sha=selected,
        definition=definition,
        version_label=definition.get("version", workflow.version_label),
        title=definition.get("title", workflow.title),
        description=definition.get("description", ""),
    )


def ensure_schedule_allowed(definition: dict[str, Any], schedule: Any) -> None:
    modes = definition.get("schedule_modes", ["on_demand", "daily", "weekly"])
    requested = schedule.cadence if schedule is not None else "on_demand"
    if not isinstance(modes, list) or requested not in modes:
        raise WorkflowInputError(f"workflow does not support {requested} scheduling")
