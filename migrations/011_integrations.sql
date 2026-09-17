CREATE TABLE integration_connections (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    provider_key text NOT NULL
        CHECK (provider_key IN ('analytics.gsc', 'infra.github')),
    status text NOT NULL DEFAULT 'connected'
        CHECK (status IN ('connected', 'needs_attention')),
    external_account_id text,
    external_account_label text,
    configuration jsonb NOT NULL DEFAULT '{}'::jsonb,
    credential_ciphertext bytea,
    credential_key_version text,
    connected_by_clerk_user_id text NOT NULL
        CHECK (connected_by_clerk_user_id ~ '^user_[A-Za-z0-9]+$'),
    last_checked_at timestamptz,
    last_error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, provider_key),
    CHECK (
        (credential_ciphertext IS NULL AND credential_key_version IS NULL)
        OR (credential_ciphertext IS NOT NULL AND credential_key_version IS NOT NULL)
    )
);

CREATE INDEX integration_connections_project_idx
    ON integration_connections (project_id, provider_key);

CREATE TABLE integration_auth_attempts (
    token_hash text PRIMARY KEY CHECK (length(token_hash) = 64),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    provider_key text NOT NULL
        CHECK (provider_key IN ('analytics.gsc', 'infra.github')),
    clerk_user_id text NOT NULL CHECK (clerk_user_id ~ '^user_[A-Za-z0-9]+$'),
    pkce_verifier_ciphertext bytea,
    expires_at timestamptz NOT NULL,
    used_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (expires_at > created_at)
);

CREATE INDEX integration_auth_attempts_project_idx
    ON integration_auth_attempts (project_id, provider_key, expires_at DESC);

CREATE TABLE integration_call_receipts (
    execution_key text PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    run_id uuid REFERENCES workflow_runs(id) ON DELETE SET NULL,
    connection_id uuid REFERENCES integration_connections(id) ON DELETE SET NULL,
    provider_key text NOT NULL
        CHECK (provider_key IN ('analytics.gsc', 'infra.github')),
    capability text NOT NULL,
    request_fingerprint text NOT NULL CHECK (length(request_fingerprint) = 64),
    status text NOT NULL CHECK (status IN ('started', 'completed', 'failed')),
    provider_request_id text,
    response_summary jsonb,
    error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX integration_call_receipts_project_idx
    ON integration_call_receipts (project_id, created_at DESC);

CREATE TABLE integration_webhook_deliveries (
    provider_key text NOT NULL CHECK (provider_key = 'infra.github'),
    delivery_id text NOT NULL,
    project_id uuid REFERENCES projects(id) ON DELETE SET NULL,
    event_type text NOT NULL,
    payload_sha256 text NOT NULL CHECK (length(payload_sha256) = 64),
    status text NOT NULL CHECK (status IN ('accepted', 'ignored', 'failed')),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (provider_key, delivery_id)
);
