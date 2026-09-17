"""Executable default/private layout examples; neither activates a private workflow."""

import json
from copy import deepcopy
from dataclasses import replace

import pytest
from test_procedure_publication import HistoryStorage

from tin_lite.catalog import BUILTIN_WORKFLOWS
from tin_lite.procedures import load_pinned_codex_procedure
from tin_lite.workflow_packages import (
    MAX_DEFINITION_BYTES,
    PACKAGE_FORMAT,
    decode_workflow_source,
    export_workflow_package,
    load_workflow_source,
    package_digest,
    relative_path,
)

KEY = "research.deep_dive"
PATH = f"workflow_packages/{KEY}/workflow.json"


def example():
    builtin = next(w for w in BUILTIN_WORKFLOWS if w.key == KEY)
    definition, resources = builtin.definition_and_resource_files()
    files = export_workflow_package(definition, resources)
    return builtin, definition, resources, files


async def load(storage, revision, path=PATH):
    return await load_pinned_codex_procedure(
        storage=storage, repo_id=storage.repo.id, commit_sha=revision, definition_path=path
    )


async def test_default_export_and_private_equivalent_preserve_effective_contract(tmp_path):
    builtin, definition, resources, exported = example()
    original = deepcopy(definition)
    storage = HistoryStorage()
    legacy_revision = storage.repo.edit(
        {builtin.definition_path: json.dumps(definition).encode(), **resources}
    )
    legacy = await load(storage, legacy_revision, builtin.definition_path)
    revision = storage.repo.edit(exported)
    package = await load(storage, revision)
    assert package == legacy
    assert decode_workflow_source(exported[PATH], definition_path=PATH).definition == definition
    assert definition == original
    assert json.loads(exported[PATH])["definition"]["procedure"]["prompt_path"] == "PROMPT.md"
    # Same bytes can be copied to a source checkout, without executing or activating them.
    for path, content in exported.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    copied = {path: (tmp_path / path).read_bytes() for path in exported}
    assert package_digest(copied, definition_path=PATH) == package_digest(
        exported, definition_path=PATH
    )

    private_key = "private.research_digest"
    private_path = f"workflow_packages/{private_key}/workflow.json"
    manifest = json.loads(exported[PATH])
    manifest["definition"]["key"] = private_key
    private = {
        path.replace(f"/{KEY}/", f"/{private_key}/"): content for path, content in exported.items()
    }
    private[private_path] = json.dumps(manifest).encode()
    private_revision = storage.repo.edit(private)
    resolved = await load(storage, private_revision, private_path)
    assert replace(resolved, workflow_key=KEY) == legacy
    # Project ownership is not inferred from a folder or manifest field; this is loader parity only.
    assert storage.repo.writes == 0
    # Later unrelated edits do not change the selected version or recipe fingerprint.
    storage.repo.edit({"notes.md": b"Unrelated project edit"})
    assert await load(storage, revision) == legacy
    assert package_digest(copied, definition_path=PATH) == package_digest(
        exported, definition_path=PATH
    )
    changed = {**exported, f"workflow_packages/{KEY}/PROMPT.md": b"Different instructions"}
    assert package_digest(changed, definition_path=PATH) != package_digest(
        exported, definition_path=PATH
    )


@pytest.mark.parametrize(
    "path",
    [
        "../escape",
        "/absolute",
        "skills/../escape",
        "skills//file",
        "skills/./file",
        "skills\\file",
        "https://example.test/resource",
        ".git/config",
        "skills/\x00file",
    ],
)
def test_package_paths_are_local_and_normalized(path):
    with pytest.raises(ValueError):
        relative_path(path)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda m: m.update(package_format="future"),
        lambda m: m.pop("package_format"),
        lambda m: m.update(unrecognized=True),
        lambda m: m["definition"]["procedure"].update(prompt_path="../PROMPT.md"),
        lambda m: m["definition"]["procedure"].update(skill_files=["../outside.md"]),
        lambda m: m["definition"]["procedure"].update(skill_files=["PROMPT.md"]),
        lambda m: m["definition"]["procedure"].update(skill_files=["skills/one/SKILL.md"] * 63),
        lambda m: m["definition"]["procedure"].update(
            skill_files=m["definition"]["procedure"]["skill_files"] * 2
        ),
        lambda m: m["definition"].update(key="other.key"),
    ],
)
def test_package_rejects_unknown_format_and_escaping_or_ambiguous_resources(mutation):
    manifest = json.loads(example()[3][PATH])
    mutation(manifest)
    with pytest.raises(ValueError):
        decode_workflow_source(json.dumps(manifest).encode(), definition_path=PATH)


@pytest.mark.parametrize(
    "field",
    [
        {"type": "string", "$ref": "https://example.test/schema", "maxLength": 20},
        {"type": "string", "pattern": "(a+)+$", "maxLength": 20},
        {"type": "string", "anyOf": [], "maxLength": 20},
        {"type": "string"},
        {"type": "string", "maxLength": 32001},
        {"type": "array", "items": {"type": "string", "maxLength": 100}},
        {"type": "array", "maxItems": 65, "items": {"type": "string", "maxLength": 100}},
        {"type": "array", "maxItems": 10, "items": {"type": "object"}},
        {"type": "string", "format": "custom", "maxLength": 20},
        {"type": "string", "enum": list(map(str, range(65)))},
    ],
)
def test_new_package_input_language_is_bounded(field):
    manifest = json.loads(example()[3][PATH])
    manifest["definition"]["input_schema"]["properties"]["question"] = field
    with pytest.raises(ValueError):
        decode_workflow_source(json.dumps(manifest).encode(), definition_path=PATH)


@pytest.mark.parametrize(
    "change",
    [
        ("PROMPT.md", None),
        ("PROMPT.md", ("120000", b"/outside/prompt")),
        ("PROMPT.md", ("160000", b"submodule")),
        ("skills", ("120000", b"/outside/skills")),
        ("workflow.json", ("120000", b"/outside/manifest")),
        ("PROMPT.md", b"x" * 32001),
        ("PROMPT.md", b"\xff"),
        ("workflow.json", b"x" * (MAX_DEFINITION_BYTES + 1)),
    ],
)
async def test_package_loader_rejects_missing_unsafe_or_oversized_files(change):
    storage = HistoryStorage()
    files = example()[3]
    files[f"workflow_packages/{KEY}/{change[0]}"] = change[1]
    revision = storage.repo.edit(files)
    with pytest.raises(ValueError):
        await load(storage, revision)


async def test_declared_skill_contents_and_total_size_are_validated():
    storage = HistoryStorage()
    files = example()[3]
    manifest = json.loads(files[PATH])
    skill = manifest["definition"]["procedure"]["skill_files"][0]
    invalid = {**files, f"workflow_packages/{KEY}/{skill}": b"No frontmatter"}
    with pytest.raises(ValueError, match="frontmatter"):
        await load(storage, storage.repo.edit(invalid))
    for index in range(3):
        path = f"skills/research-deep-dive/references/large-{index}.md"
        manifest["definition"]["procedure"]["skill_files"].append(path)
        files[f"workflow_packages/{KEY}/{path}"] = b"x" * 50000
    files[PATH] = json.dumps(manifest).encode()
    with pytest.raises(ValueError, match="too large"):
        await load(storage, storage.repo.edit(files))


def test_digest_and_export_require_exact_declared_files():
    _, definition, resources, files = example()
    with pytest.raises(ValueError, match="declared"):
        export_workflow_package(definition, {**resources, "unlisted.md": b"not declared"})
    with pytest.raises(ValueError, match="declared"):
        package_digest({**files, "unrelated.md": b"unrelated"}, definition_path=PATH)
    assert len(package_digest(files, definition_path=PATH)) == 64


async def test_native_definition_has_no_uploaded_executor_and_legacy_bytes_still_load():
    builtin = next(w for w in BUILTIN_WORKFLOWS if w.key == "project.memory")
    definition, resources = builtin.definition_and_resource_files()
    assert not resources
    files = export_workflow_package(definition, resources)
    path = f"workflow_packages/{builtin.key}/workflow.json"
    storage = HistoryStorage()
    revision = storage.repo.edit(files)
    source = await load_workflow_source(
        storage=storage, repo_id=storage.repo.id, commit_sha=revision, definition_path=path
    )
    assert source.definition == definition and not source.resource_paths
    assert source.package_format == PACKAGE_FORMAT
    legacy = decode_workflow_source(
        json.dumps(definition).encode(), definition_path=builtin.definition_path
    )
    assert legacy.definition == definition and legacy.package_format is None
    with pytest.raises(ValueError, match="implementation code"):
        export_workflow_package(definition, {"executor.py": b"print('no')"})
