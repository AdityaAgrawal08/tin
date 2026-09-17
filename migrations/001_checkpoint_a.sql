CREATE TABLE IF NOT EXISTS tin_schema_migrations (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS projects (
    id uuid PRIMARY KEY,
    name text NOT NULL,
    state_repo_id text NOT NULL UNIQUE,
    canonical_branch text NOT NULL DEFAULT 'main',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS workflow_runs (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id),
    workflow_name text NOT NULL CHECK (workflow_name = 'content.design_md'),
    temporal_workflow_id text NOT NULL UNIQUE,
    thread_id text NOT NULL,
    generation bigint NOT NULL CHECK (generation > 0),
    status text NOT NULL CHECK (status IN ('pending', 'running', 'succeeded', 'failed')),
    sandbox_id text,
    ephemeral_branch text,
    expected_head_sha text,
    canonical_commit_sha text,
    artifact_path text,
    artifact_ref text,
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    UNIQUE (project_id, thread_id, generation)
);

CREATE TABLE IF NOT EXISTS session_leases (
    project_id uuid NOT NULL REFERENCES projects(id),
    thread_id text NOT NULL,
    generation bigint NOT NULL,
    lease_owner text NOT NULL,
    fencing_token bigint GENERATED ALWAYS AS IDENTITY,
    sandbox_id text NOT NULL,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    released_at timestamptz,
    PRIMARY KEY (project_id, thread_id, generation),
    UNIQUE (fencing_token)
);

CREATE UNIQUE INDEX IF NOT EXISTS one_active_session_lease
ON session_leases (project_id, thread_id)
WHERE active;

CREATE TABLE IF NOT EXISTS step_executions (
    execution_key text PRIMARY KEY,
    operation text NOT NULL,
    status text NOT NULL CHECK (status IN ('started', 'completed', 'failed')),
    result jsonb,
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS broker_grants (
    token_hash text PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES workflow_runs(id),
    sandbox_id text NOT NULL,
    expires_at timestamptz NOT NULL,
    last_used_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS broker_grants_run_idx ON broker_grants (run_id);

CREATE TABLE IF NOT EXISTS run_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES workflow_runs(id),
    event_type text NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS run_events_run_idx ON run_events (run_id, id);
