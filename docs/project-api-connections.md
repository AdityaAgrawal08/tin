# Project API connections — Slice C

Slice C extends the isolated `workflow.code` executor with project-owned connections.
Ordinary Python controls the workflow. Tin executes it independently of the authoring agent.
Existing Codex procedures, one-off tasks, review rules and recorded Temporal commands are unchanged.
Private execution remains restricted to the existing explicit pilot projects.

## Secure setup

In **Integrations → Custom API**, choose a connection name, HTTPS origin, authentication
method, project secret name and allowed HTTP methods. Bearer tokens and named API-key
headers are supported. OAuth integrations continue using their existing adapters and
credentials; do not copy those credentials into custom connections.

Paste a key into the password field, or select a local env file and check only the names
this project needs. Parsing happens locally; values are masked, unchecked names are not
submitted, and replacing existing names requires an explicit selection. Values are literal:
no shell evaluation, interpolation, multiline values or project-file upload. Imports support
up to 32 selected names, each at most 8 KB; a project holds at most 128 named secrets.

Saving does **not** call the provider or purchase a test request. The connection says
**saved · not verified** until an actual workflow request succeeds. Rotation clears that
verification. Missing secrets stop execution. Disconnecting a custom connection leaves its
named secret available for deliberate reuse; deleting the secret makes dependent connections
need attention. Secret deletion is available through the authenticated metadata/revision API.

The same service backs the dashboard and local helper:

```bash
uv run python -m tin_lite.secret_import \
  --project PROJECT_UUID --file ./selected.env --name CRM_API_KEY --dry-run

uv run python -m tin_lite.secret_import \
  --project PROJECT_UUID --file ./selected.env --name CRM_API_KEY
```

The helper requests an explicitly supplied Tin OAuth/session token through a hidden prompt;
`--token-file` accepts an explicitly chosen token file. It never searches coding-agent
credential stores. `--replace` permits replacement of selected existing names after a fresh
metadata read; concurrent changes still conflict. Values never appear in output or arguments.
For self-hosts, supply `--url https://your-tin-origin`.

MCP `prepare_project_connection` returns the secure setup link and secret **metadata**.
Secret values have no MCP input/output schema. Agents must never ask the user to paste keys
into their conversation or put env files in project state.

HTTP endpoints under `/api/projects/{project_id}/connections`:

- `GET /secrets`: names, credential revisions, encryption key IDs, update times.
- `PUT /secrets`: atomic selected entries `{name, value, expected_revision}`.
- `DELETE /secrets/{name}/{revision}`: remove that exact revision.
- `PUT /custom.api.<name>`: configuration and expected connection revision; no key value.

Membership in the exact project is required. Workspace administration does not grant access.
Malformed secret requests return fixed diagnostics, without FastAPI's input echo.

## Code contract

Use the same required `integration_requirements` used by registered workflows, and bind each
provider once in `code.services`:

```json
{
  "integration_requirements": [
    {"provider_key": "custom.api.crm", "capabilities": ["http.read"], "required": true}
  ],
  "code": {
    "services": {
      "crm": {"provider_key": "custom.api.crm", "max_calls": 2, "max_response_bytes": 8000}
    }
  }
}
```

This is an excerpt; the complete package is in
[`code_connection_example`](../src/tin_lite/code_connection_example/workflow.json), also
returned by MCP `get_workflow_authoring_guide` as `connection_example_files`.
It fetches three account records, filters them, makes one managed classification call,
validates the IDs and business rule, and publishes `reports/custom/CONNECTED_ACCOUNTS.md`.

```python
response = await ctx.services.request(
    service="crm",
    step="fetch_accounts",
    path="/accounts",
    method="GET",
    params={"limit": 3},
)
accounts = response["data"]["accounts"]
```

Requests accept an origin-relative path, scalar query parameters and an optional JSON body.
No author-supplied destination, headers, auth or redirects are accepted. Tin resolves and pins
public DNS addresses before attaching credentials, verifies TLS for the approved hostname,
ignores proxy environment variables, refuses compressed responses and bounds returned JSON.
Credential echoes are withheld. Non-redirect HTTP responses return `{status, data}` so code
can validate business results. Invalid, oversized, unavailable or ambiguous results stop the
attempt and do not silently repeat the external request.

GET requires `http.read`. POST/PUT/PATCH/DELETE require `http.write` **and** that exact method
on the connection. Where supported, configuring `Idempotency-Key` or `X-Idempotency-Key`
sends a stable Tin-derived operation ID. This does not promise universal exactly-once writes.
No live external-write acceptance is claimed by this slice.

Up to four service bindings and eight total calls share the existing 60-second compute window.
Requests are at most 16 KB; each response is bounded to 1–64 KB. Sandboxes remain networkless
and credential-free. Only the trusted activity invokes the gateway through the existing
protected E2B controller channel and checks the run, membership, lease and fencing tuple.

## Existing adapters and contributions

`ctx.services.call(service=..., step=..., operation=..., arguments={...})` reuses existing
project connections with this explicit reviewed mapping:

| Provider | Operation | Required capability |
| --- | --- | --- |
| `analytics.gsc` | `sites.list` | `sites.list` |
| `analytics.gsc` | `search_analytics.read` | `search_analytics.read` |
| `infra.github` | `repositories.list` | `repositories.list` |
| `workspace.google` | `gmail.messages.search`, `gmail.thread.read` | `gmail.messages.read` |
| `workspace.google` | `calendar.events.list` | `calendar.events.read` |

Adapter arguments are those of the bounded `IntegrationService` operation; project, run,
account, connection and execution IDs are supplied by Tin. Email sends and GitHub delivery
retain their established workflow-specific contracts. Existing procedures keep their existing
run tools; this slice exposes the generic client to explicit code workflows only.

To contribute a provider adapter:

1. Add its project-owned connection definition and smallest useful capabilities to
   `integrations.py`; credentials remain encrypted on the switchboard.
2. Implement bounded operations with safe diagnostics and explicit result contracts. Keep
   OAuth/account selection and provider-specific semantics inside the adapter.
3. Add a reviewed operation mapping in `code_services.py` and allowed capabilities in
   `workflow_code.py`. Do not dynamically import plugins or dispatch arbitrary method names.
4. Test authorization, revocation, bounded results, failure ambiguity, recovery and usage
   with fixtures before one authorized small live read. Document costs and limitations.

A custom HTTP binding is useful without a registry contribution. It is not automatically
interchangeable with an adapter: authored code must explicitly map the operation and response
shape. Attio and Clay adapters are not included.

## Recovery and costs

Stable step IDs and fingerprints bind responses in the existing `effect_receipts` table
(`code_service_call_v1`). The first call pins the connection/account/configuration for the
run. Completed responses replay after worker or sandbox loss. A changed request or connection
conflicts. An unresolved attempt blocks new steps too; changing an ID cannot purchase it again.
Credential rotation under the same name retains the binding, while permission checks still
run before cached results. Cancellation stops further calls; it does not recall a provider
write that was already accepted. No execution-state files or second orchestration engine exist.

Connected-provider observations use the existing Postgres usage projection, marked
`connected_api`, `billed_by: connected_provider`, with unknown provider costs left null.
These requests never create Tin credit operations. Model calls use the existing priced
route, usage recorder and ledger separately. Model-free bounded compute still works at zero
Tin credits; an external account may have its own provider charges.

## Encryption and operations

Migration `036_project_secrets.sql` adds one small project secret table and extends the
existing connection provider constraint. Secret values use the existing AES-GCM cipher and
`TIN_LITE_INTEGRATION_CREDENTIAL_KEY`, with project/name/credential-revision associated data.
The credential revision is a UUID; the encryption key ID is a separate nonsecret fingerprint.
Provider keys never enter workflow source, sandbox environments, Temporal history or logs.

Back up encrypted database state **and** the encryption key. Restoring only one cannot recover
values. A missing/wrong key fails closed. `rewrap_project_secrets` is an operator-only primitive
for drained setup/execution: back up both keys, rewrap in a transaction, switch the configured
key, verify, then retire the old key. It preserves credential revisions and bindings. The
reverse operation supports recovery. Existing OAuth/test-identity credentials also use this
key and require their established re-encryption process; this helper alone is not a global
key rotation. No production key was changed for Slice C.

Apply the additive migration before deploying. Rolling the runtime back retains the table,
connections and receipts; no destructive schema rollback is necessary. Keep the private-project
allowlist unchanged. The outer Temporal workflow and existing history commands do not change.

## Verification

- Local fixture tests cover encrypted storage, selected import, membership, revision conflicts,
  rotation, request origin/header/path bounds, private addresses, redirects, credential echoes,
  payload limits, unknown attempts, capability limits and external-cost separation.
- Real Postgres saturation tests leave one pool slot available and exercise competing setup
  updates, custom service replay/new calls, and the existing Google adapter's refresh, receipts
  and authorization-failure path. These operations reuse the held connection and do not wait
  for another pool slot. Supplier HTTP responses are fixtures in these tests.
- Real Chromium verifies the packaged setup form with synthetic API/auth responses, in light
  and dark themes and at phone width. The in-app browser was unavailable in this session.
