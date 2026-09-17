CREATE TABLE project_file_changes (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    request_id uuid NOT NULL,
    actor_clerk_user_id text NOT NULL CHECK (actor_clerk_user_id ~ '^user_[A-Za-z0-9]+$'),
    client_id text,
    operation text NOT NULL CHECK (operation IN ('commit', 'revert')),
    request_fingerprint text NOT NULL CHECK (length(request_fingerprint) = 64),
    expected_head_sha text NOT NULL CHECK (length(expected_head_sha) = 40),
    status text NOT NULL CHECK (status IN ('started', 'completed', 'failed')),
    commit_sha text CHECK (commit_sha IS NULL OR length(commit_sha) = 40),
    summary jsonb,
    error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, request_id)
);

CREATE INDEX project_file_changes_project_idx
    ON project_file_changes (project_id, created_at DESC);
