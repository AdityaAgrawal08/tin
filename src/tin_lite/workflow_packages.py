"""A versioned file layout, normalized to the existing workflow definition contract.

This module neither activates definitions nor authorizes private execution. Package-relative
resources are mapped to the existing procedure paths without making a second stored copy.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from tin_lite.workflow_inputs import validate_input_schema

PACKAGE_FORMAT = "tin-workflow-package-v1"
MAX_DEFINITION_BYTES = 512_000
MAX_PACKAGE_FILES = 64


def validate_package_input_schema(schema: dict[str, Any]) -> None:
    """The new authoring format is a bounded language, not arbitrary JSON Schema."""
    if not isinstance(schema, dict) or set(schema) - {
        "type",
        "additionalProperties",
        "properties",
        "required",
    }:
        raise ValueError("unsupported package input-schema keyword")
    properties = schema.get("properties")
    if not isinstance(properties, dict) or not 1 <= len(properties) <= 32:
        raise ValueError("package input schema must have 1-32 fields")
    keywords = {
        "type",
        "title",
        "description",
        "default",
        "enum",
        "format",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "items",
        "minItems",
        "maxItems",
        "uniqueItems",
        "x-tin-ui",
    }

    def field(value, *, item=False):
        if not isinstance(value, dict) or set(value) - keywords:
            raise ValueError("unsupported package input-schema keyword")
        kind = value.get("type")
        if item and kind != "string":
            raise ValueError("package arrays may only contain strings")
        if "enum" in value and (
            not isinstance(value["enum"], list) or not 1 <= len(value["enum"]) <= 64
        ):
            raise ValueError("package enums must have 1-64 entries")
        if "format" in value and value["format"] not in {
            "uuid",
            "date",
            "date-time",
            "uri",
            "email",
            "hostname",
        }:
            raise ValueError("unsupported package input format")
        if kind == "string" and "enum" not in value:
            maximum = value.get("maxLength", 36 if value.get("format") == "uuid" else None)
            if type(maximum) is not int or not 1 <= maximum <= 32_000:
                raise ValueError("package text inputs require a bounded maxLength")
        if kind == "array":
            maximum = value.get("maxItems")
            if type(maximum) is not int or not 1 <= maximum <= 64:
                raise ValueError("package arrays require a bounded maxItems")
            field(value.get("items"), item=True)
        elif "items" in value:
            raise ValueError("only package arrays may declare items")

    for name, value in properties.items():
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name):
            raise ValueError("package input field name is invalid")
        field(value)
    validate_input_schema(schema)


def relative_path(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 500:
        raise ValueError("workflow resource path is invalid")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {".", "..", ".git"} for part in path.parts)
        or "\\" in value
        or ":" in value
        or any(ord(char) < 32 for char in value)
    ):
        raise ValueError("workflow resource path must be package-relative")
    return value


@dataclass(frozen=True)
class WorkflowSource:
    definition: dict[str, Any]
    resource_paths: dict[str, str]
    package_format: str | None = None


def decode_workflow_source(raw: bytes, *, definition_path: str) -> WorkflowSource:
    if not raw or len(raw) > MAX_DEFINITION_BYTES:
        raise ValueError("workflow definition exceeds its byte limit")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("workflow definition must be a JSON object")
    if "package_format" not in value:
        if definition_path.startswith("workflow_packages/"):
            raise ValueError("workflow package requires an explicit format version")
        return WorkflowSource(value, {})
    if set(value) != {"package_format", "definition"} or value["package_format"] != PACKAGE_FORMAT:
        raise ValueError("unsupported workflow package format")
    definition = deepcopy(value["definition"])
    if not isinstance(definition, dict):
        raise ValueError("workflow package needs a definition")
    key = definition.get("key")
    if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,79}", key):
        raise ValueError("workflow package key is invalid")
    root = f"workflow_packages/{key}"
    if relative_path(definition_path) != f"{root}/workflow.json":
        raise ValueError("workflow package path must match its key")
    validate_package_input_schema(definition.get("input_schema", {}))
    resources = {}
    if definition.get("executor") == "codex.procedure":
        procedure = definition.get("procedure")
        if not isinstance(procedure, dict):
            raise ValueError("workflow package needs a procedure contract")
        if procedure.get("prompt_path") != "PROMPT.md" or procedure.get("skills_path") != "skills":
            raise ValueError("workflow package prompt/skills paths are invalid")
        files = procedure.get("skill_files")
        if not isinstance(files, list) or not 1 <= len(files) <= MAX_PACKAGE_FILES - 2:
            raise ValueError("workflow package has an invalid resource count")
        legacy_root = f"procedures/{key}"
        for path in ["PROMPT.md", *files]:
            path = relative_path(path)
            resources[f"{legacy_root}/{path}"] = f"{root}/{path}"
        procedure["prompt_path"] = f"{legacy_root}/PROMPT.md"
        procedure["skills_path"] = f"{legacy_root}/skills"
        procedure["skill_files"] = [f"{legacy_root}/{path}" for path in files]
        from tin_lite.procedures import validate_codex_procedure_definition

        validate_codex_procedure_definition(definition)
    elif definition.get("executor") == "workflow.code":
        from tin_lite.workflow_code import validate_code_definition

        spec = validate_code_definition(definition)
        resources = {path: f"{root}/{path}" for path in spec.files}
    elif "code" in definition:
        raise ValueError("only workflow.code packages may upload code")
    elif "procedure" in definition:
        raise ValueError("native workflow packages cannot upload a procedure implementation")
    return WorkflowSource(definition, resources, PACKAGE_FORMAT)


async def load_workflow_source(*, storage, repo_id, commit_sha, definition_path) -> WorkflowSource:
    reader = (
        storage.read_workflow_resource
        if definition_path.startswith("workflow_packages/")
        else storage.read_canonical_artifact
    )
    raw = await reader(repo_id=repo_id, commit_sha=commit_sha, path=definition_path)
    return decode_workflow_source(raw, definition_path=definition_path)


def export_workflow_package(
    definition: dict[str, Any], resources: dict[str, bytes]
) -> dict[str, bytes]:
    """Export a compatible existing contract; no registry or filesystem mutations."""
    body = deepcopy(definition)
    key = body["key"]
    root = f"workflow_packages/{key}"
    exported = {}
    if body.get("executor") == "codex.procedure":
        from tin_lite.procedures import validate_codex_procedure_definition

        spec = validate_codex_procedure_definition(body)
        declared = {spec.prompt_path, *spec.skill_files}
        if set(resources) != declared:
            raise ValueError("export resources must match the declared workflow files")
        prefix = f"procedures/{key}/"
        for path in declared:
            exported[f"{root}/{path.removeprefix(prefix)}"] = resources[path]
        body["procedure"]["prompt_path"] = "PROMPT.md"
        body["procedure"]["skills_path"] = "skills"
        body["procedure"]["skill_files"] = [p.removeprefix(prefix) for p in spec.skill_files]
    elif body.get("executor") == "workflow.code":
        from tin_lite.workflow_code import validate_code_definition, validate_code_resources

        spec = validate_code_definition(body)
        validate_code_resources(spec, resources)
        exported.update({f"{root}/{path}": raw for path, raw in resources.items()})
    elif resources:
        raise ValueError("native package export does not include uploaded implementation code")
    path = f"{root}/workflow.json"
    exported[path] = (
        json.dumps({"package_format": PACKAGE_FORMAT, "definition": body}, indent=2, sort_keys=True)
        + "\n"
    ).encode()
    decode_workflow_source(exported[path], definition_path=path)
    return exported


def package_digest(files: dict[str, bytes], *, definition_path: str) -> str:
    """A recipe fingerprint independent of unrelated project commits and parent directories."""
    source = decode_workflow_source(files[definition_path], definition_path=definition_path)
    if source.package_format != PACKAGE_FORMAT:
        raise ValueError("a package digest requires the versioned package layout")
    paths = [definition_path, *source.resource_paths.values()]
    if set(files) != set(paths):
        raise ValueError("package digest accepts exactly the declared package files")
    root = str(PurePosixPath(definition_path).parent) + "/"
    digest = hashlib.sha256()
    for path in sorted(paths):
        name, content = path.removeprefix(root).encode(), files[path]
        digest.update(len(name).to_bytes(8, "big") + name)
        digest.update(len(content).to_bytes(8, "big") + content)
    return digest.hexdigest()
