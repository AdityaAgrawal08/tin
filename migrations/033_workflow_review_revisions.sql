-- Review control is metadata; article bytes remain immutable code.storage artifacts.
ALTER TABLE workflow_runs DROP CONSTRAINT workflow_runs_status_check;
ALTER TABLE workflow_runs ADD CONSTRAINT workflow_runs_status_check CHECK
    (status IN ('pending', 'running', 'needs_input', 'paused', 'stopped',
                'succeeded', 'failed', 'superseded'));
ALTER TABLE workflow_runs
    ADD COLUMN review_root_run_id uuid REFERENCES workflow_runs(id),
    ADD COLUMN review_source_run_id uuid REFERENCES workflow_runs(id),
    ADD COLUMN review_version integer NOT NULL DEFAULT 1 CHECK (review_version > 0);
CREATE INDEX workflow_review_lineage ON workflow_runs(review_root_run_id, review_version);

CREATE TABLE workflow_review_commands (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id),
    request_id uuid NOT NULL,
    actor_clerk_user_id text NOT NULL,
    source_run_id uuid NOT NULL UNIQUE REFERENCES workflow_runs(id),
    root_run_id uuid NOT NULL REFERENCES workflow_runs(id),
    artifact_run_id uuid NOT NULL REFERENCES workflow_runs(id),
    coordinator_run_id uuid REFERENCES workflow_runs(id),
    action text NOT NULL CHECK (action IN ('approve', 'revise', 'cancel')),
    request_digest text NOT NULL,
    review_token text NOT NULL,
    artifact jsonb NOT NULL CHECK (jsonb_typeof(artifact) = 'object'),
    feedback text NOT NULL DEFAULT '' CHECK (length(feedback) <= 8000),
    reference_files jsonb NOT NULL DEFAULT '[]' CHECK
        (jsonb_typeof(reference_files) = 'array' AND jsonb_array_length(reference_files) <= 8),
    successor_run_id uuid UNIQUE REFERENCES workflow_runs(id),
    dispatch_state text NOT NULL DEFAULT 'pending' CHECK
        (dispatch_state IN ('pending', 'dispatched', 'received')),
    created_at timestamptz NOT NULL DEFAULT now(),
    dispatched_at timestamptz,
    received_at timestamptz,
    UNIQUE (project_id, request_id),
    CHECK ((action = 'revise') = (successor_run_id IS NOT NULL)),
    CHECK (action <> 'revise' OR length(trim(feedback)) > 0)
);
CREATE INDEX workflow_review_dispatch ON workflow_review_commands(created_at)
    WHERE dispatch_state <> 'received';
