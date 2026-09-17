CREATE TABLE content_programs (
    project_workflow_id uuid PRIMARY KEY REFERENCES project_workflows(id),
    project_id uuid NOT NULL REFERENCES projects(id),
    initial_run_id uuid NOT NULL UNIQUE REFERENCES workflow_runs(id),
    plan_revision text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE content_plan_batches (
    project_workflow_id uuid NOT NULL REFERENCES content_programs(project_workflow_id),
    batch_id text NOT NULL,
    run_id uuid NOT NULL UNIQUE REFERENCES workflow_runs(id),
    source_revision text NOT NULL,
    item_ids jsonb NOT NULL,
    status text NOT NULL DEFAULT 'reserved' CHECK (status IN ('reserved', 'prepared')),
    artifact_revision text,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (project_workflow_id, batch_id)
);

CREATE TABLE content_plan_revisions (
    id uuid PRIMARY KEY,
    project_workflow_id uuid NOT NULL REFERENCES content_programs(project_workflow_id),
    project_id uuid NOT NULL REFERENCES projects(id),
    request_fingerprint text NOT NULL,
    base_revision text NOT NULL,
    batch_ids jsonb NOT NULL,
    instruction text NOT NULL,
    context_paths jsonb NOT NULL,
    actor_clerk_user_id text NOT NULL,
    run_id uuid UNIQUE REFERENCES workflow_runs(id),
    preview_revision text,
    applied_revision text,
    apply_base_revision text,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'applying', 'applied', 'discarded')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX content_plan_one_pending_revision
    ON content_plan_revisions(project_workflow_id) WHERE status IN ('pending', 'applying');
