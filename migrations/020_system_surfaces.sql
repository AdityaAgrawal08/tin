CREATE TABLE saved_workflow_templates (
    clerk_user_id text NOT NULL REFERENCES tin_users(clerk_user_id) ON DELETE CASCADE,
    workflow_id uuid NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (clerk_user_id, workflow_id)
);

CREATE INDEX saved_workflow_templates_workflow_idx
ON saved_workflow_templates (workflow_id, clerk_user_id);

CREATE TABLE run_decisions (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    run_id uuid NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
    kind text NOT NULL DEFAULT 'review'
        CHECK (kind IN ('review', 'select', 'response')),
    title text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 160),
    explanation text NOT NULL DEFAULT '' CHECK (char_length(explanation) <= 2000),
    consequence text NOT NULL DEFAULT '' CHECK (char_length(consequence) <= 1000),
    items jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(items) = 'array'),
    response_schema jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(response_schema) = 'object'),
    feedback_supported boolean NOT NULL DEFAULT false,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'applied', 'dismissed')),
    response jsonb CHECK (response IS NULL OR jsonb_typeof(response) = 'object'),
    deadline_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    applied_at timestamptz,
    applied_by_clerk_user_id text
        CHECK (applied_by_clerk_user_id IS NULL
               OR applied_by_clerk_user_id ~ '^user_[A-Za-z0-9]+$'),
    UNIQUE (run_id, id),
    CHECK (
        (status = 'pending' AND applied_at IS NULL AND applied_by_clerk_user_id IS NULL)
        OR (status <> 'pending' AND applied_at IS NOT NULL)
    )
);

CREATE INDEX run_decisions_project_pending_idx
ON run_decisions (project_id, created_at, id)
WHERE status = 'pending';

CREATE TABLE project_mcp_usage (
    project_id uuid PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    clerk_user_id text NOT NULL
        CHECK (clerk_user_id ~ '^user_[A-Za-z0-9]+$'),
    oauth_client_id text,
    tool_name text NOT NULL CHECK (char_length(tool_name) BETWEEN 1 AND 100),
    used_at timestamptz NOT NULL DEFAULT now()
);
