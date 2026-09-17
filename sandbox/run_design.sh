#!/usr/bin/env bash
set -euo pipefail

# Old entrypoints must fail before accessing credentials or project content.
echo "The legacy pooled OAuth design runner is disabled" >&2
exit 64
