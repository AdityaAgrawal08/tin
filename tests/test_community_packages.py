"""A contributed package is checked from a checkout, and never activated by checking it."""

import json
import re
from pathlib import Path

import pytest

from tin_lite.catalog import BUILTIN_WORKFLOWS
from tin_lite.community import (
    CODE_SUFFIXES,
    CONTRIBUTED_SUFFIXES,
    ContributedPackage,
    discover,
    validate,
    validate_all,
)
from tin_lite.workflow_packages import export_workflow_package

KEY = "research.deep_dive"


def stage(root: Path, key: str = KEY) -> Path:
    """Write one contributed package to a checkout, exported from a registered workflow."""
    builtin = next(workflow for workflow in BUILTIN_WORKFLOWS if workflow.key == KEY)
    definition, resources = builtin.definition_and_resource_files()
    files = export_workflow_package(definition, resources)
    if key != KEY:
        manifest = json.loads(files[f"workflow_packages/{KEY}/workflow.json"])
        manifest["definition"]["key"] = key
        files = {path.replace(f"/{KEY}/", f"/{key}/"): value for path, value in files.items()}
        files[f"workflow_packages/{key}/workflow.json"] = json.dumps(manifest).encode()
    for path, content in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return root / "workflow_packages" / key


def rewrite_format(package_path: Path) -> None:
    manifest = json.loads((package_path / "workflow.json").read_text())
    manifest["package_format"] = "tin-workflow-package-v99"
    (package_path / "workflow.json").write_text(json.dumps(manifest))


async def test_an_exported_workflow_is_a_valid_contributed_package(tmp_path):
    package_path = stage(tmp_path)
    results = await validate_all(tmp_path)
    assert [(package.key, error) for package, error in results] == [(KEY, None)]
    assert discover(tmp_path / "workflow_packages") == [
        ContributedPackage(key=KEY, path=package_path)
    ]


async def test_a_checkout_without_contributions_passes(tmp_path):
    (tmp_path / "workflow_packages").mkdir()
    (tmp_path / "workflow_packages" / "README.md").write_text("How to contribute a workflow.\n")
    assert await validate_all(tmp_path) == []
    assert discover(tmp_path / "workflow_packages") == []


async def test_two_contributions_are_reported_separately(tmp_path):
    stage(tmp_path)
    second = stage(tmp_path, key="growth.example_play")
    (second / "PROMPT.md").unlink()
    results = {package.key: error for package, error in await validate_all(tmp_path)}
    assert results[KEY] is None
    assert isinstance(results["growth.example_play"], ValueError)


@pytest.mark.parametrize(
    "break_it,expected",
    [
        (lambda p: (p / "scratch.md").write_text("notes"), "never lists it"),
        (lambda p: (p / "score.py").write_text("print(1)"), "not a file type"),
        (lambda p: (p / "PROMPT.md").unlink(), "missing"),
        (lambda p: (p / "PROMPT.md").write_bytes(b""), "invalid size"),
        (lambda p: (p / "workflow.json").write_text("{}"), "explicit format version"),
        (rewrite_format, "unsupported workflow package format"),
    ],
)
async def test_a_broken_contribution_is_refused(tmp_path, break_it, expected):
    package_path = stage(tmp_path)
    break_it(package_path)
    with pytest.raises(ValueError, match=expected):
        await validate(ContributedPackage(key=KEY, path=package_path), root=tmp_path)


async def test_a_symlinked_resource_is_refused(tmp_path):
    package_path = stage(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("Content the package does not own.\n")
    (package_path / "PROMPT.md").unlink()
    (package_path / "PROMPT.md").symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        await validate(ContributedPackage(key=KEY, path=package_path), root=tmp_path)


def test_contributed_packages_carry_text_a_reviewer_can_read():
    assert ".py" not in CONTRIBUTED_SUFFIXES
    assert ".sh" not in CONTRIBUTED_SUFFIXES
    assert ".py" in CODE_SUFFIXES and ".csv" in CODE_SUFFIXES
    assert ".sh" not in CODE_SUFFIXES


async def test_this_repository_validates():
    assert all(error is None for _, error in await validate_all())


@pytest.mark.parametrize("missing", ["deleted", "renamed"])
async def test_missing_manifests_do_not_disappear(tmp_path, missing):
    package = stage(tmp_path)
    manifest = package / "workflow.json"
    if missing == "deleted":
        manifest.unlink()
    else:
        manifest.rename(package / "renamed.json")
    results = await validate_all(tmp_path)
    assert len(results) == 1 and results[0][0].key == KEY
    assert "missing" in str(results[0][1])


@pytest.mark.parametrize("broken", [False, True])
async def test_symlinked_packages_do_not_disappear(tmp_path, broken):
    stage(tmp_path)
    target = tmp_path / "workflow_packages" / KEY
    if broken:
        target = tmp_path / "does-not-exist"
    (tmp_path / "workflow_packages" / "growth.link").symlink_to(target)
    results = {package.key: error for package, error in await validate_all(tmp_path)}
    assert results[KEY] is None
    assert "symlink" in str(results["growth.link"])


async def test_unexpected_root_files_are_reported(tmp_path):
    stage(tmp_path)
    (tmp_path / "workflow_packages" / "loose.json").write_text("{}")
    results = {package.key: error for package, error in await validate_all(tmp_path)}
    assert results[KEY] is None
    assert "must be a directory" in str(results["loose.json"])


@pytest.mark.parametrize("field", ["title", "description", "version", "schedule_modes"])
async def test_required_metadata_cannot_be_missing(tmp_path, field):
    package = stage(tmp_path)
    path = package / "workflow.json"
    manifest = json.loads(path.read_bytes())
    del manifest["definition"][field]
    path.write_text(json.dumps(manifest))
    results = await validate_all(tmp_path)
    assert field in str(results[0][1])


@pytest.mark.parametrize(
    "field,value,expected",
    [
        ("title", " ", "title"),
        ("title", "x" * 121, "title"),
        ("description", [], "description"),
        ("version", 1, "version"),
        ("kind", "task", "not tasks"),
        ("human_review", "yes", "review"),
        ("human_review", {"eligible": "false"}, "review"),
        ("human_review", {"eligible": False, "typo": True}, "review"),
        ("human_review", {"eligible": True, "summary": 12}, "review"),
        ("human_review", {"eligible": True, "summary": "x" * 1001}, "review"),
        ("schedule_modes", "daily", "schedule_modes"),
        ("schedule_modes", [], "schedule_modes"),
        ("schedule_modes", ["on_demand", "on_demand"], "schedule_modes"),
        ("schedule_modes", ["hourly"], "schedule_modes"),
        ("schedule_modes", [{}], "schedule_modes"),
        ("integration_requirements", "github", "integration_requirements"),
        ("integration_requirements", [{}], "integration requirement"),
        (
            "integration_requirements",
            [{"provider_key": "infra.github", "capabilities": ["fake"], "required": True}],
            "unsupported capability",
        ),
        ("prerequisites", "research.deep_dive", "prerequisites"),
        ("prerequisites", [{"kind": "unknown"}], "prerequisite"),
    ],
)
async def test_invalid_surrounding_metadata_is_refused(tmp_path, field, value, expected):
    package = stage(tmp_path)
    path = package / "workflow.json"
    manifest = json.loads(path.read_bytes())
    manifest["definition"][field] = value
    path.write_text(json.dumps(manifest))
    results = await validate_all(tmp_path)
    assert expected in str(results[0][1])


async def test_community_check_does_not_apply_private_only_policies(tmp_path):
    package = stage(tmp_path)
    path = package / "workflow.json"
    manifest = json.loads(path.read_bytes())
    manifest["definition"]["schedule_modes"] = ["on_demand", "daily", "weekly"]
    manifest["definition"]["human_review"] = {"eligible": True, "summary": "Review report"}
    path.write_text(json.dumps(manifest))
    assert [(package.key, error) for package, error in await validate_all(tmp_path)] == [
        (KEY, None)
    ]


@pytest.mark.parametrize("shape", ["missing_root", "missing_folder", "file", "symlink"])
async def test_bad_roots_fail_with_a_cli_diagnostic(tmp_path, capsys, shape):
    from tin_lite.cli import _validate_community

    root = tmp_path
    if shape == "missing_root":
        root = tmp_path / "missing"
    elif shape == "file":
        (root / "workflow_packages").write_text("not a folder")
    elif shape == "symlink":
        (root / "workflow_packages").symlink_to(tmp_path)
    with pytest.raises(SystemExit) as error:
        await _validate_community(root)
    assert error.value.code == 1
    output = capsys.readouterr().out
    assert "FAIL" in output and "directory" in output
    assert "No contributed" not in output


async def test_cli_reports_all_packages_and_exits_nonzero(tmp_path, capsys):
    from tin_lite.cli import _validate_community

    stage(tmp_path)
    bad = stage(tmp_path, "growth.broken")
    (bad / "workflow.json").unlink()
    with pytest.raises(SystemExit) as error:
        await _validate_community(tmp_path)
    assert error.value.code == 1
    output = capsys.readouterr().out
    assert f"ok    {KEY}" in output and "FAIL  growth.broken" in output
    assert "1 of 2 packages are valid" in output


def readme_example_files(*, private=False):
    """Exercise the actual copyable README example, not a parallel test-only recipe."""
    from tin_lite.community import REPOSITORY_ROOT

    readme = (REPOSITORY_ROOT / "workflow_packages" / "README.md").read_text()
    manifest = json.loads(re.search(r"```json\n(.*?)\n```", readme, re.S)[1])
    if private:
        manifest["definition"]["key"] = "custom.example_play"
    key = manifest["definition"]["key"]
    prompt, skill = re.findall(r"```markdown\n(.*?)\n```", readme, re.S)
    return {
        f"workflow_packages/{key}/workflow.json": json.dumps(manifest).encode(),
        f"workflow_packages/{key}/PROMPT.md": prompt.encode(),
        f"workflow_packages/{key}/skills/example-play/SKILL.md": skill.encode(),
    }


@pytest.mark.parametrize("private", [False, True])
async def test_readme_example_validates(tmp_path, private):
    from tin_lite.private_workflows import validate_private_definition
    from tin_lite.workflow_packages import decode_workflow_source

    files = readme_example_files(private=private)
    for path, raw in files.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    results = await validate_all(tmp_path)
    assert len(results) == 1 and results[0][1] is None
    if private:
        path = "workflow_packages/custom.example_play/workflow.json"
        source = decode_workflow_source(files[path], definition_path=path)
        validate_private_definition(source.definition)


@pytest.mark.parametrize("model_steps", [False, True])
async def test_code_and_model_workflows_are_public_contribution_types(tmp_path, model_steps):
    from tin_lite.workflow_code import example_files

    for path, content in example_files("reports.order_summary", model_steps=model_steps).items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    results = await validate_all(tmp_path)
    assert len(results) == 1
    assert results[0][1] is None


async def test_contributed_python_is_parsed_never_imported(tmp_path):
    from tin_lite.workflow_code import example_files

    for path, content in example_files().items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    source = tmp_path / "workflow_packages/custom.order_report/main.py"
    marker = tmp_path / "never-created"
    source.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
    assert (await validate_all(tmp_path))[0][1] is None
    assert not marker.exists()
    source.write_text("def run(:\n")
    assert "invalid Python syntax" in str((await validate_all(tmp_path))[0][1])


async def test_oversized_manifest_is_rejected_before_reading_it(tmp_path, monkeypatch):
    from tin_lite.workflow_packages import MAX_DEFINITION_BYTES

    package = stage(tmp_path)
    (package / "workflow.json").write_bytes(b" " * (MAX_DEFINITION_BYTES + 1))

    def unexpected_read(_path):
        pytest.fail("oversized manifest should not be read")

    monkeypatch.setattr(Path, "read_bytes", unexpected_read)
    results = await validate_all(tmp_path)
    assert "byte limit" in str(results[0][1])
