from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError


class WorkflowInputError(ValueError):
    """A workflow input or published input schema is outside Tin's contract."""


def client_input_schema(definition: dict[str, Any]) -> dict[str, Any]:
    """The shared HTTP/MCP invocation schema excludes server-bound project identity."""
    schema = deepcopy(definition.get("input_schema", {}))
    if not isinstance(schema, dict):
        return {}
    if isinstance(schema.get("properties"), dict):
        schema["properties"].pop("project_id", None)
    if isinstance(schema.get("required"), list):
        schema["required"] = [key for key in schema["required"] if key != "project_id"]
    return schema


_SUPPORTED_UI_CONTROLS = {
    "string": {"text", "textarea", "select"},
    "boolean": {"segmented"},
    "integer": {"counter", "number"},
    "number": {"counter", "number"},
    "array": set(),
}


def validate_input_schema(schema: dict[str, Any]) -> None:
    """Validate the JSON Schema and the deliberately small UI-renderable subset."""
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise WorkflowInputError(f"workflow input schema is invalid: {exc.message}") from exc
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise WorkflowInputError(
            "workflow input schema must be a closed object with additionalProperties false"
        )
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        raise WorkflowInputError("workflow input schema must define object properties")
    project = properties.get("project_id")
    if not isinstance(project, dict) or project.get("type") != "string":
        raise WorkflowInputError("workflow input schema must define the bound project_id")
    supported = {"string", "boolean", "integer", "number", "array"}
    for name, field in properties.items():
        if not isinstance(field, dict) or field.get("type") not in supported:
            raise WorkflowInputError(f"workflow input {name} uses an unsupported field shape")
        ui = field.get("x-tin-ui")
        if ui is not None:
            if not isinstance(ui, dict):
                raise WorkflowInputError(f"workflow input {name} x-tin-ui must be an object")
            unknown = set(ui) - {"control", "order"}
            if unknown:
                raise WorkflowInputError(
                    f"workflow input {name} x-tin-ui contains unsupported hints: "
                    f"{', '.join(sorted(unknown))}"
                )
            control = ui.get("control")
            if control is not None and control not in _SUPPORTED_UI_CONTROLS[field["type"]]:
                raise WorkflowInputError(
                    f"workflow input {name} cannot use the {control!r} control"
                )
            if control == "select" and not isinstance(field.get("enum"), list):
                raise WorkflowInputError(f"workflow input {name} select controls require an enum")
            order = ui.get("order")
            if order is not None and (not isinstance(order, int) or isinstance(order, bool)):
                raise WorkflowInputError(f"workflow input {name} x-tin-ui order must be an integer")
        if field.get("type") == "array":
            items = field.get("items")
            if not isinstance(items, dict) or items.get("type") != "string":
                raise WorkflowInputError(
                    f"workflow input {name} must be an array of strings for dashboard editing"
                )


def normalize_workflow_inputs(
    *,
    schema: dict[str, Any],
    project_id: UUID,
    inputs: dict[str, Any] | None,
) -> dict[str, Any]:
    """Bind project identity, apply top-level defaults, and validate user inputs."""
    validate_input_schema(schema)
    normalized = deepcopy(inputs or {})
    if "project_id" in normalized:
        raise WorkflowInputError("project_id is bound by Tin and cannot be supplied as input")
    properties = schema["properties"]
    for name, field in properties.items():
        if name != "project_id" and name not in normalized and "default" in field:
            normalized[name] = deepcopy(field["default"])
    candidate = {"project_id": str(project_id), **normalized}
    try:
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(candidate)
    except ValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path)
        label = f"workflow input {location}" if location else "workflow input"
        raise WorkflowInputError(f"{label}: {exc.message}") from exc
    return normalized
