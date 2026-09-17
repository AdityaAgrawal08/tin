#!/usr/bin/env python3
"""Tin-owned post-agent check, installed outside the editable repository."""

import base64
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# The image builder copies this pure verifier module alongside this script. The
# switchboard independently repeats the same validation before any GitHub effect.
from technical_title_rules import verify_title_change  # noqa: E402


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
    workspace = Path("/home/user/project")
    for path, before in prepared["originals"].items():
        after = (workspace / path).read_bytes().decode("utf-8")
        if result.get("outcome") == "no_change":
            if after != before:
                raise ValueError("A no-change result modified source HTML")
        else:
            verify_title_change(before, after)


if __name__ == "__main__":
    main()
