#!/usr/bin/env bash
set -euo pipefail

project_id="tin-lite-integrations"

if ! command -v gcloud >/dev/null 2>&1; then
  echo "gcloud is required" >&2
  exit 69
fi

resolved_project="$({
  gcloud projects describe "${project_id}" \
    --format='value(projectId)' \
    --quiet
} 2>/dev/null)"
if [[ "${resolved_project}" != "${project_id}" ]]; then
  echo "refusing to configure any project except ${project_id}" >&2
  exit 65
fi

gcloud services enable \
  gmail.googleapis.com \
  calendar-json.googleapis.com \
  --project "${project_id}" \
  --quiet

gcloud services list \
  --enabled \
  --project "${project_id}" \
  --filter='config.name:(gmail.googleapis.com OR calendar-json.googleapis.com)' \
  --format='value(config.name)' \
  --sort-by='config.name'
