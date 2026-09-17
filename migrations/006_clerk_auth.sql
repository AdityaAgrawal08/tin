CREATE TABLE tin_users (
    clerk_user_id text PRIMARY KEY,
    first_signed_in_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    CHECK (clerk_user_id ~ '^user_[A-Za-z0-9]+$')
);

CREATE TABLE project_memberships (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    clerk_user_id text NOT NULL CHECK (clerk_user_id ~ '^user_[A-Za-z0-9]+$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, clerk_user_id)
);

CREATE INDEX project_memberships_user_idx
    ON project_memberships (clerk_user_id, project_id);

CREATE TABLE project_invitations (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    email text NOT NULL CHECK (email = lower(email) AND length(email) BETWEEN 3 AND 320),
    token_hash text NOT NULL UNIQUE CHECK (length(token_hash) = 64),
    created_by_clerk_user_id text NOT NULL
        CHECK (created_by_clerk_user_id ~ '^user_[A-Za-z0-9]+$'),
    accepted_by_clerk_user_id text
        CHECK (accepted_by_clerk_user_id ~ '^user_[A-Za-z0-9]+$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    accepted_at timestamptz,
    revoked_at timestamptz,
    CHECK (expires_at > created_at),
    CHECK (
        (accepted_at IS NULL AND accepted_by_clerk_user_id IS NULL)
        OR (accepted_at IS NOT NULL AND accepted_by_clerk_user_id IS NOT NULL)
    )
);

CREATE INDEX project_invitations_project_idx
    ON project_invitations (project_id, created_at DESC);

ALTER TABLE workflow_runs
    ADD COLUMN started_by_clerk_user_id text
        CHECK (started_by_clerk_user_id ~ '^user_[A-Za-z0-9]+$'),
    ADD COLUMN reviewed_by_clerk_user_id text
        CHECK (reviewed_by_clerk_user_id ~ '^user_[A-Za-z0-9]+$');
