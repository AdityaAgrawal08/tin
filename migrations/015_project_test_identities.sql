CREATE TABLE project_test_identities (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    created_by_run_id uuid NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
    target_host text NOT NULL CHECK (length(target_host) BETWEEN 1 AND 253),
    label text NOT NULL CHECK (length(label) BETWEEN 1 AND 120),
    email text NOT NULL CHECK (length(email) BETWEEN 3 AND 320),
    auth_kind text NOT NULL DEFAULT 'password'
        CHECK (auth_kind IN ('password', 'magic_link', 'otp')),
    username text CHECK (username IS NULL OR length(username) BETWEEN 1 AND 320),
    password_ciphertext bytea,
    credential_key_version text,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'active', 'blocked', 'failed', 'retired')),
    status_note text CHECK (status_note IS NULL OR length(status_note) <= 2000),
    verified_at timestamptz,
    last_used_run_id uuid REFERENCES workflow_runs(id) ON DELETE SET NULL,
    last_used_at timestamptz,
    notes text CHECK (notes IS NULL OR length(notes) <= 4000),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (created_by_run_id),
    CHECK (
        (password_ciphertext IS NULL AND credential_key_version IS NULL)
        OR (password_ciphertext IS NOT NULL AND credential_key_version IS NOT NULL)
    )
);

CREATE INDEX project_test_identities_project_idx
    ON project_test_identities (project_id, target_host, status, created_at DESC);
