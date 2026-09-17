CREATE TABLE chat_messages (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    request_id uuid NOT NULL,
    role text NOT NULL CHECK (role IN ('user', 'assistant')),
    source text NOT NULL CHECK (source IN ('founder', 'luna')),
    content text NOT NULL CHECK (char_length(content) BETWEEN 1 AND 32000),
    author_clerk_user_id text
        CHECK (author_clerk_user_id ~ '^user_[A-Za-z0-9]+$'),
    response_id text,
    routed_workflow_key text,
    run_id uuid REFERENCES workflow_runs(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, request_id, role),
    CHECK (
        (role = 'user'
            AND source = 'founder'
            AND author_clerk_user_id IS NOT NULL
            AND response_id IS NULL
            AND routed_workflow_key IS NULL
            AND run_id IS NULL)
        OR
        (role = 'assistant'
            AND source = 'luna'
            AND author_clerk_user_id IS NULL)
    )
);

CREATE INDEX chat_messages_project_created_idx
    ON chat_messages (project_id, created_at DESC, id DESC);

ALTER TABLE workflow_runs
    ADD COLUMN start_idempotency_key text
        CHECK (char_length(start_idempotency_key) BETWEEN 1 AND 200);

CREATE UNIQUE INDEX workflow_runs_start_idempotency_idx
    ON workflow_runs (project_id, start_idempotency_key)
    WHERE start_idempotency_key IS NOT NULL;
