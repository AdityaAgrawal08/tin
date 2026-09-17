CREATE TABLE project_workflows (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    workflow_id uuid NOT NULL REFERENCES workflows(id),
    definition_commit_sha text NOT NULL,
    name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 120),
    inputs jsonb NOT NULL DEFAULT '{}'::jsonb,
    input_schema jsonb NOT NULL,
    schedule jsonb,
    status text NOT NULL DEFAULT 'provisioning'
        CHECK (status IN ('provisioning', 'active', 'paused', 'failed', 'archived')),
    temporal_schedule_id text UNIQUE,
    next_run_at timestamptz,
    last_error text,
    request_id uuid NOT NULL,
    created_by_clerk_user_id text NOT NULL
        CHECK (created_by_clerk_user_id ~ '^user_[A-Za-z0-9]+$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, request_id),
    CHECK (jsonb_typeof(inputs) = 'object'),
    CHECK (jsonb_typeof(input_schema) = 'object'),
    CHECK (schedule IS NULL OR jsonb_typeof(schedule) = 'object')
);

CREATE INDEX project_workflows_project_idx
ON project_workflows (project_id, created_at, id)
WHERE status <> 'archived';

ALTER TABLE workflow_runs
    ADD COLUMN project_workflow_id uuid REFERENCES project_workflows(id),
    ADD COLUMN trigger_source text NOT NULL DEFAULT 'manual'
        CHECK (trigger_source IN ('manual', 'chat', 'mcp', 'schedule')),
    ADD COLUMN scheduled_for timestamptz;

CREATE INDEX workflow_runs_project_workflow_idx
ON workflow_runs (project_workflow_id, created_at DESC)
WHERE project_workflow_id IS NOT NULL;
