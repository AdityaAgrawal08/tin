# API-only Codex execution

All new Codex compute requires the protected API route. The switchboard holds
`TIN_LITE_LUNA_API_KEY`; each sandbox controller receives only a temporary run-bound
Responses relay grant. Project commands run as a separate user without that grant.
Provider keys never enter sandbox environments, artifacts, or Temporal history.

The pooled ChatGPT broker, authentication fetch/write-back endpoints, native-login
cache handling, reseeding script, and deployment dependency on `auth.json` are removed.
No session-rotation service or replacement login is required to run Tin.

## Existing work

Historical authentication and billing pins are immutable. An OAuth-pinned run cannot
start new compute and is never silently switched to API billing. Durable artifacts,
retained output, review gates, and historical usage remain readable. The old migration
files and grant table remain for schema-history compatibility and deletion cleanup;
there is no API that creates or authorizes a pooled-auth grant.

Self-host operators configure the trusted API credential and explicitly enable the
existing API project setting. Hosted defaults already enable supported new runs.
This change does not activate live payments or change prices and budgets.

## Deployment

Drain active sandbox work, deploy the application and API-only sandbox runners together,
and preserve existing project/review state. Remove retired pooled-auth settings from
the service configuration and remove the old credential from the service account's
readable storage. Rebuild the isolated, browser API and Studio API images without
changing model, CLI, or runtime dependency pins.

Verify that the removed broker routes return 404, startup works without a login file,
OAuth pins cannot create compute, API execution remains bounded and accounted, and
saved output remains recoverable. The TLS proxy and its destination fence remain
required. Never restore an OAuth broker or plaintext proxy to regain availability.

Previously issued login credentials should be revoked separately at their provider.
Deleting a local file or removing code does not revoke copied credentials. This is
one-time operator account cleanup, not application functionality. No real credential
belongs in the repository, shared reports, or acceptance logs.
