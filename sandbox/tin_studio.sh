#!/usr/bin/env bash
# The `tin-studio` entry point inside the studio sandbox: runs the toolkit with its own venv.
set -euo pipefail
export TIN_STUDIO_RESVG=/opt/tin-lite/studio/resvg
exec /opt/tin-lite/studio-venv/bin/python /opt/tin-lite/studio/tin_studio.py "$@"
