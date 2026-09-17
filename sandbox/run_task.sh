#!/usr/bin/env bash
set -euo pipefail

umask 077

if [[ "${1:-}" == "--check-api" ]]; then
  printf 'TIN_TASK_API_READY_V1\n'
  exit 0
fi

if [[ -n "${OPENAI_API_KEY:-}" || -n "${CODEX_API_KEY:-}" || \
      -n "${TIN_LITE_LUNA_API_KEY:-}" || -n "${ANTHROPIC_API_KEY:-}" || \
      -n "${GEMINI_API_KEY:-}" || -n "${OPENROUTER_API_KEY:-}" || -n "${FAL_KEY:-}" || \
      -n "${TIN_LITE_INTEGRATION_CREDENTIAL_KEY:-}" || \
      -n "${TIN_LITE_GOOGLE_OAUTH_CLIENT_SECRET:-}" || \
      -n "${TIN_LITE_GITHUB_APP_PRIVATE_KEY_PATH:-}" || \
      -n "${TIN_LITE_GITHUB_WEBHOOK_SECRET:-}" ]]; then
  echo "API-key Codex authentication is forbidden" >&2
  exit 70
fi

required=(
  TIN_EXECUTION_KEY TIN_SANDBOX_ID
  TIN_CANONICAL_URL TIN_CANONICAL_AUTH_HEADER TIN_CANONICAL_BRANCH
  TIN_EPHEMERAL_URL TIN_EPHEMERAL_AUTH_HEADER TIN_EPHEMERAL_BRANCH
  TIN_TASK_CONTEXT_B64
)
if [[ "${TIN_PROCEDURE_ISOLATED:-}" != "1" || -n "${TIN_BROKER_GRANT:-}" ||
      -z "${TIN_CODEX_API_URL:-}" || -z "${TIN_CODEX_API_GRANT:-}" ]]; then
  echo "Codex runs require protected API execution" >&2
  exit 64
fi
required+=(TIN_CODEX_API_URL TIN_CODEX_API_GRANT)
for name in "${required[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    echo "missing required task setting: ${name}" >&2
    exit 64
  fi
done

workspace=/home/user/project
# Codex writes rollouts under /home/user/.codex/sessions; the switchboard captures them
# before the sandbox is killed. Cleanup must never remove that directory.
result_file=/home/user/.tin-lite/task-result.json

cleanup() {
  exit_code=$?
  trap - EXIT
  rm -f "${result_file}"
  exit "${exit_code}"
}
trap cleanup EXIT

mkdir -p /home/user/.codex /home/user/.tin-lite
python3 /opt/tin-lite/codex_api_config.py

rm -rf "${workspace}"
GIT_TERMINAL_PROMPT=0 \
GIT_CONFIG_COUNT=1 \
GIT_CONFIG_KEY_0=http.extraHeader \
GIT_CONFIG_VALUE_0="${TIN_CANONICAL_AUTH_HEADER}" \
  git clone --filter=blob:none --single-branch --branch "${TIN_CANONICAL_BRANCH}" \
    "${TIN_CANONICAL_URL}" "${workspace}" >/dev/null

git -C "${workspace}" remote add ephemeral "${TIN_EPHEMERAL_URL}"
git -C "${workspace}" config user.name "Tin Task Agent"
git -C "${workspace}" config user.email "task-agent@tin.local"

set +e
remote_line="$(
  GIT_TERMINAL_PROMPT=0 \
  GIT_CONFIG_COUNT=1 \
  GIT_CONFIG_KEY_0=http.extraHeader \
  GIT_CONFIG_VALUE_0="${TIN_EPHEMERAL_AUTH_HEADER}" \
    git -C "${workspace}" ls-remote --exit-code \
      ephemeral "refs/heads/${TIN_EPHEMERAL_BRANCH}" 2>/dev/null
)"
remote_status=$?
set -e
if [[ "${remote_status}" -eq 0 ]]; then
  commit_sha="${remote_line%%[[:space:]]*}"
  GIT_TERMINAL_PROMPT=0 \
  GIT_CONFIG_COUNT=1 \
  GIT_CONFIG_KEY_0=http.extraHeader \
  GIT_CONFIG_VALUE_0="${TIN_EPHEMERAL_AUTH_HEADER}" \
    git -C "${workspace}" fetch --quiet ephemeral "${commit_sha}"
  git -C "${workspace}" checkout --detach FETCH_HEAD >/dev/null
elif [[ "${remote_status}" -ne 2 ]]; then
  echo "could not inspect the task checkpoint branch" >&2
  exit 68
fi

TIN_TASK_RESULT_PATH="${result_file}" \
  env -u OPENAI_API_KEY -u CODEX_API_KEY -u TIN_LITE_LUNA_API_KEY \
    -u ANTHROPIC_API_KEY -u GEMINI_API_KEY -u TIN_LITE_INTEGRATION_CREDENTIAL_KEY \
    -u TIN_LITE_GOOGLE_OAUTH_CLIENT_SECRET -u TIN_LITE_GITHUB_APP_PRIVATE_KEY_PATH \
    -u TIN_LITE_GITHUB_WEBHOOK_SECRET /opt/tin-lite/task-app-server

if [[ -n "$(git -C "${workspace}" status --porcelain)" ]]; then
  git -C "${workspace}" add -A
  git -C "${workspace}" commit -m "Save project.task checkpoint" >/dev/null
fi

if ! git -C "${workspace}" diff --quiet "origin/${TIN_CANONICAL_BRANCH}" HEAD; then
  GIT_TERMINAL_PROMPT=0 \
  GIT_CONFIG_COUNT=1 \
  GIT_CONFIG_KEY_0=http.extraHeader \
  GIT_CONFIG_VALUE_0="${TIN_EPHEMERAL_AUTH_HEADER}" \
    git -C "${workspace}" push ephemeral "HEAD:${TIN_EPHEMERAL_BRANCH}" >/dev/null
  printf 'TIN_TASK_HAS_CHANGES=1\n'
else
  printf 'TIN_TASK_HAS_CHANGES=0\n'
fi

base64 -w 0 "${result_file}" | sed 's/^/TIN_TASK_RESULT=/'
printf '\n'
