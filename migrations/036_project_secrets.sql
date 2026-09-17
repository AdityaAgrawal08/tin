-- Named project secrets complement the existing project connection registry. Values
-- are write-only at the product boundary; credential revisions are not key versions.
CREATE TABLE project_secrets (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name text NOT NULL CHECK (name ~ '^[A-Z][A-Z0-9_]{0,63}$'),
    revision uuid NOT NULL,
    ciphertext bytea NOT NULL,
    encryption_key_id text NOT NULL,
    updated_by_clerk_user_id text NOT NULL CHECK (updated_by_clerk_user_id ~ '^user_[A-Za-z0-9]+$'),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, name)
);

ALTER TABLE integration_connections DROP CONSTRAINT integration_connections_provider_key_check;
ALTER TABLE integration_connections ADD CONSTRAINT integration_connections_provider_key_check
    CHECK (provider_key IN ('analytics.gsc', 'infra.github', 'workspace.google')
           OR provider_key ~ '^custom\.api\.[a-z][a-z0-9_]{0,47}$');
