"""Paid E2B verifier smoke test; no model, GitHub write, or customer-file modification.

Uses the current committed Tin template with synthetic public substitutions and a
synthetic description. This proves the installed checker, NOT live PR delivery.
"""

import asyncio
import base64
import hashlib
import json
import os
import subprocess
from pathlib import Path

from dotenv import dotenv_values
from e2b import AsyncSandbox

from tin_lite.technical_build_profile import match_profile
from tin_lite.technical_metadata_rules import DESCRIPTION_CHECK

ROOT = Path(__file__).resolve().parents[1]


async def main():
    archive = await asyncio.to_thread(
        subprocess.check_output, ["git", "archive", "--format=tar.gz", "HEAD"], cwd=ROOT
    )
    source_path = "src/tin_lite/static/index.html"
    template = (ROOT / source_path).read_text()
    served = (
        template.replace("{{ASSET_VERSION}}", "public-build")
        .replace("{{CLERK_PUBLISHABLE_KEY}}", "public-key")
        .replace("{{CLERK_FRONTEND_API_URL}}", "https://public.example")
        .replace("{{BILLING_ENABLED}}", "true")
    )
    matched = match_profile(
        archive,
        [{"html": served, "sha256": hashlib.sha256(served.encode()).hexdigest()}],
        DESCRIPTION_CHECK,
    )
    assert matched and matched["verification_profile"]["kind"] == "hatchling-wheel-html-v1"
    prepared = {**matched, "selection": {"finding": {"check_id": DESCRIPTION_CHECK}}}
    context = base64.b64encode(
        json.dumps({"workspace": {"technical_fix": prepared}}).encode()
    ).decode()
    sandbox = await AsyncSandbox.create(
        "tin-lite-codex",
        timeout=300,
        metadata={"purpose": "technical-metadata-verifier-acceptance"},
        network={"deny_out": lambda context: [context.all_traffic]},
        api_key=os.environ.get("E2B_API_KEY") or dotenv_values(ROOT / ".env")["E2B_API_KEY"],
    )
    try:
        for local, remote in [
            ("sandbox/verify_technical_metadata.py", "verify-technical-metadata.py"),
            ("src/tin_lite/technical_build_profile.py", "technical_build_profile.py"),
            ("src/tin_lite/technical_metadata_rules.py", "technical_metadata_rules.py"),
            ("sandbox/run_procedure.sh", "run-procedure"),
        ]:
            result = await sandbox.commands.run(f"sha256sum /opt/tin-lite/{remote}")
            assert (
                result.stdout.split()[0] == hashlib.sha256((ROOT / local).read_bytes()).hexdigest()
            )
        await sandbox.commands.run(
            "mkdir -p /home/user/project/src/tin_lite/static /home/user/.tin-lite"
        )
        await sandbox.files.write("/home/user/.tin-lite/procedure-workspace.tar.gz", archive)
        await sandbox.files.write(
            "/home/user/.tin-lite/procedure-result.json", '{"outcome":"patch"}'
        )
        after = template.replace(
            "<head>",
            '<head><meta name="description" content="Tin Lite workflow workspace '
            'for running and reviewing project workflows.">',
        )
        await sandbox.files.write("/home/user/project/" + source_path, after)
        command = (
            "/opt/tin-lite/metadata-venv/bin/python -I /opt/tin-lite/verify-technical-metadata.py"
        )
        result = await sandbox.commands.run(
            command, envs={"TIN_PROCEDURE_CONTEXT_B64": context}, timeout=120
        )
        assert result.exit_code == 0
        print("installed_hashes=true; real_wheel_before_after=true; packaged_html_verified=true")
        await sandbox.files.write("/home/user/project/" + source_path, after + "\n")
        result = await sandbox.commands.run(
            command + " >/dev/null 2>&1 && exit 9 || test $? -ne 9",
            envs={"TIN_PROCEDURE_CONTEXT_B64": context},
            timeout=30,
        )
        assert result.exit_code == 0
        print("unrelated_change_rejected=true")
        result = await sandbox.commands.run(
            "bash -n /opt/tin-lite/run-procedure && "
            "test ! -w /opt/tin-lite/verify-technical-metadata.py && "
            "test ! -w /opt/tin-lite/technical_metadata_rules.py && "
            "test ! -w /opt/tin-lite/technical_build_profile.py"
        )
        assert result.exit_code == 0
        print("runner_syntax=true; verifier_files_read_only=true")
    finally:
        await sandbox.kill()
        print("sandbox_killed=true")


if __name__ == "__main__":
    asyncio.run(main())
