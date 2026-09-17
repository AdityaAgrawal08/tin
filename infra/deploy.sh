#!/usr/bin/env bash
set -euo pipefail

: "${TIN_LITE_GCP_PROJECT:?Set TIN_LITE_GCP_PROJECT to your deployment project}"

root="$(git rev-parse --show-toplevel)"
cd "${root}"
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "tracked worktree changes must be committed before deployment" >&2
  exit 65
fi
if [[ ! -f .env ]]; then
  echo "local .env is required" >&2
  exit 66
fi
if rg -q '^OPENAI_API_KEY=' .env; then
  echo "OPENAI_API_KEY is forbidden" >&2
  exit 67
fi

github_private_key_path="$(sed -n 's/^TIN_LITE_GITHUB_APP_PRIVATE_KEY_PATH=//p' .env | tail -n 1)"
if [[ -n "${github_private_key_path}" ]]; then
  if [[ ! -f "${github_private_key_path}" ]]; then
    echo "TIN_LITE_GITHUB_APP_PRIVATE_KEY_PATH must name a readable local file" >&2
    exit 68
  fi
  if ! openssl pkey -in "${github_private_key_path}" -check -noout >/dev/null 2>&1; then
    echo "TIN_LITE_GITHUB_APP_PRIVATE_KEY_PATH is not a valid private key" >&2
    exit 68
  fi
fi

release_sha="$(git rev-parse HEAD)"
temporary_dir="$(mktemp -d)"
trap 'rm -rf "${temporary_dir}"' EXIT
git archive --format=tar.gz --output="${temporary_dir}/tin-lite-release.tar.gz" HEAD

gcloud compute scp \
  "${temporary_dir}/tin-lite-release.tar.gz" \
  .env \
  infra/install_switchboard.sh \
  infra/install_forward_proxy.sh \
  infra/proxy_policy.py \
  src/tin_lite/proxy_grants.py \
  infra/activate_release.sh \
  tin-lite-switchboard:/tmp/ \
  --project "${TIN_LITE_GCP_PROJECT}" --zone us-central1-a --quiet

if [[ -n "${github_private_key_path}" ]]; then
  gcloud compute scp \
    "${github_private_key_path}" \
    tin-lite-switchboard:/tmp/tin-lite-github-app.pem \
    --project "${TIN_LITE_GCP_PROJECT}" --zone us-central1-a --quiet
  gcloud compute ssh tin-lite-switchboard \
    --project "${TIN_LITE_GCP_PROJECT}" --zone us-central1-a --quiet \
    --command="sudo chown root:root /tmp/tin-lite-github-app.pem && \
sudo chmod 600 /tmp/tin-lite-github-app.pem"
fi

static_ip="$(gcloud compute addresses describe tin-lite-switchboard-ip \
  --project "${TIN_LITE_GCP_PROJECT}" --region us-central1 --format='value(address)')"
product_host="${TIN_LITE_PRODUCT_HOST:-app.tin.computer}"
if [[ ! "${product_host}" =~ ^[a-zA-Z0-9.-]+$ ]]; then
  echo "TIN_LITE_PRODUCT_HOST must be a DNS hostname" >&2
  exit 64
fi
gcloud compute ssh tin-lite-switchboard \
  --project "${TIN_LITE_GCP_PROJECT}" --zone us-central1-a --quiet \
  --command="sudo env TIN_LITE_STATIC_IP=${static_ip} TIN_LITE_PRODUCT_HOST=${product_host} bash /tmp/install_switchboard.sh && \
sudo mv /tmp/.env /tmp/tin-lite.env && \
sudo bash /tmp/activate_release.sh ${release_sha}"

public_host="tin-lite-switchboard.${static_ip//./-}.sslip.io"
curl --http1.1 --fail --silent --show-error --retry 20 --retry-all-errors --retry-delay 3 \
  "https://${public_host}/healthz"

product_host="${TIN_LITE_PRODUCT_HOST:-app.tin.computer}"
curl --http1.1 --fail --silent --show-error --retry 20 --retry-all-errors --retry-delay 3 \
  "https://${product_host}/healthz"
