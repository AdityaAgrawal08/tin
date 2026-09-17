ALTER TABLE integration_connections
    DROP CONSTRAINT IF EXISTS integration_connections_provider_key_check;
ALTER TABLE integration_connections
    ADD CONSTRAINT integration_connections_provider_key_check
    CHECK (provider_key IN ('analytics.gsc', 'infra.github', 'workspace.google'));

ALTER TABLE integration_auth_attempts
    DROP CONSTRAINT IF EXISTS integration_auth_attempts_provider_key_check;
ALTER TABLE integration_auth_attempts
    ADD CONSTRAINT integration_auth_attempts_provider_key_check
    CHECK (provider_key IN ('analytics.gsc', 'infra.github', 'workspace.google'));
ALTER TABLE integration_auth_attempts
    ADD COLUMN requested_capabilities jsonb NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE integration_call_receipts
    DROP CONSTRAINT IF EXISTS integration_call_receipts_provider_key_check;
ALTER TABLE integration_call_receipts
    ADD CONSTRAINT integration_call_receipts_provider_key_check
    CHECK (provider_key IN ('analytics.gsc', 'infra.github', 'workspace.google'));
ALTER TABLE integration_call_receipts
    DROP CONSTRAINT IF EXISTS integration_call_receipts_status_check;
ALTER TABLE integration_call_receipts
    ADD CONSTRAINT integration_call_receipts_status_check
    CHECK (status IN ('started', 'completed', 'failed', 'unknown'));

ALTER TABLE integration_webhook_deliveries
    DROP CONSTRAINT IF EXISTS integration_webhook_deliveries_provider_key_check;
ALTER TABLE integration_webhook_deliveries
    ADD CONSTRAINT integration_webhook_deliveries_provider_key_check
    CHECK (provider_key IN ('infra.github', 'workspace.google'));

CREATE TABLE run_tool_grants (
    token_hash text PRIMARY KEY CHECK (length(token_hash) = 64),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    run_id uuid NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
    connection_id uuid NOT NULL REFERENCES integration_connections(id) ON DELETE CASCADE,
    external_account_id text NOT NULL,
    sandbox_id text NOT NULL,
    generation bigint NOT NULL CHECK (generation > 0),
    fencing_token bigint NOT NULL CHECK (fencing_token > 0),
    provider_key text NOT NULL CHECK (provider_key = 'workspace.google'),
    capabilities jsonb NOT NULL,
    expires_at timestamptz NOT NULL,
    last_used_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (expires_at > created_at)
);

CREATE INDEX run_tool_grants_run_idx ON run_tool_grants (run_id, expires_at DESC);
