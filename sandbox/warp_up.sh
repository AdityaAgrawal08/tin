#!/usr/bin/env bash
# Start Cloudflare WARP as a local SOCKS proxy (127.0.0.1:40000) for the browser profile.
# E2B egress is IPv4-only while Cloudflare serves Turnstile challenge dependencies from
# IPv6-only hostnames, so the browser needs WARP for dual-stack reachability. Only the
# browser uses this proxy; Codex keeps reaching OpenAI through the switchboard proxy env vars.
set -euo pipefail
umask 077

log_dir="${1:?usage: warp-up <log-dir>}"

if ! command -v warp-svc >/dev/null 2>&1; then
  echo "browser profile requires cloudflare-warp in the sandbox template" >&2
  exit 69
fi

mkdir -p "${log_dir}"
sudo -n warp-svc > "${log_dir}/warp-svc.log" 2>&1 < /dev/null &
disown

registered=""
for _ in $(seq 1 30); do
  if sudo -n warp-cli --accept-tos registration new >/dev/null 2>&1; then
    registered=1
    break
  fi
  sleep 1
done
if [[ -z "${registered}" ]]; then
  echo "WARP registration did not succeed" >&2
  exit 71
fi

sudo -n warp-cli --accept-tos mode proxy >/dev/null
sudo -n warp-cli --accept-tos connect >/dev/null

connected=""
for _ in $(seq 1 60); do
  if sudo -n warp-cli --accept-tos status 2>/dev/null | grep -q Connected; then
    connected=1
    break
  fi
  sleep 1
done
if [[ -z "${connected}" ]]; then
  echo "WARP proxy did not connect; the browser has no IPv6 egress" >&2
  exit 71
fi

echo "WARP_OK=true"
