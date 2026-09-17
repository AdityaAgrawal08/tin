#!/usr/bin/env python3
"""Offline verification from the trusted, digest-pinned snapshot, never agent build scripts."""

import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

# -I excludes the checkout, user site and PYTHONPATH. Only root-owned Tin modules
# are added; no repository module or build hook is imported by this verifier.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from technical_build_profile import (  # noqa: E402
    STATIC,
    WHEEL,
    archive_files,
    render,
    snapshot_digest,
    wheel_package,
)
from technical_metadata_rules import verify_metadata_change  # noqa: E402


def build(root, package, paths):
    for source in (root / package).rglob("*.py"):
        compile(source.read_bytes(), str(source), "exec", dont_inherit=True)
    subprocess.run(  # noqa: S603
        [sys.executable, "-I", "-m", "hatchling", "build", "-t", "wheel", "-d", str(root / "dist")],
        cwd=root,
        check=True,
        timeout=60,
        capture_output=True,
        env={"PATH": "/usr/bin:/bin", "SOURCE_DATE_EPOCH": "1700000000"},
    )
    wheels = list((root / "dist").glob("*.whl"))
    if len(wheels) != 1:
        raise ValueError("Expected one built wheel.")
    with zipfile.ZipFile(wheels[0]) as wheel:
        return {path: wheel.read(path.removeprefix("src/")).decode("utf-8") for path in paths}


def verify(prepared, archive, changes, *, no_change=False):
    profile = prepared["verification_profile"]
    files = archive_files(archive)
    if snapshot_digest(files) != profile["snapshot_sha256"]:
        raise ValueError("The verification snapshot changed.")
    check = prepared["selection"]["finding"]["check_id"]
    originals = prepared["originals"]
    if set(changes) != set(originals):
        raise ValueError("Unexpected verification files.")
    for path, before in originals.items():
        if files[path].decode("utf-8") != before:
            raise ValueError("The original HTML does not match the pinned snapshot.")
        if no_change:
            if changes[path] != before:
                raise ValueError("A no-change result modified HTML.")
        else:
            verify_metadata_change(before, changes[path], check)
    if no_change:
        return
    if profile["kind"] == WHEEL:
        package = wheel_package(files["pyproject.toml"])
        if package != profile["package"] or "hatch.toml" in files:
            raise ValueError("The wheel profile changed.")
        with tempfile.TemporaryDirectory(prefix="tin-metadata-") as temporary:
            built = []
            for label, html in (("before", originals), ("after", changes)):
                root = Path(temporary) / label
                for path, raw in files.items():
                    destination = root / path
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(html[path].encode() if path in html else raw)
                built.append(build(root, package, originals))
            if built != [originals, changes]:
                raise ValueError("The built wheel did not preserve the verified HTML.")
    elif profile["kind"] != STATIC:
        raise ValueError("Unsupported verification profile.")
    for observation in profile["observations"]:
        path, values = observation["path"], observation["values"]
        before, after = render(originals[path], values), render(changes[path], values)
        if hashlib.sha256(before.encode()).hexdigest() != observation["sha256"]:
            raise ValueError("The rendered template no longer matches the observed page.")
        verify_metadata_change(before, after, check)


def main():
    context_path = os.environ.get("TIN_PROCEDURE_CONTEXT_PATH")
    if context_path:
        context = json.loads(Path(context_path).read_bytes())
    else:
        context = json.loads(
            base64.b64decode(os.environ["TIN_PROCEDURE_CONTEXT_B64"], validate=True)
        )
    prepared = context["workspace"]["technical_fix"]
    result = json.loads(Path("/home/user/.tin-lite/procedure-result.json").read_text())
    changes = {
        path: (Path("/home/user/project") / path).read_bytes().decode("utf-8")
        for path in prepared["originals"]
    }
    verify(
        prepared,
        Path("/home/user/.tin-lite/procedure-workspace.tar.gz").read_bytes(),
        changes,
        no_change=result.get("outcome") == "no_change",
    )
    print("Tin metadata verification passed.")


if __name__ == "__main__":
    main()
