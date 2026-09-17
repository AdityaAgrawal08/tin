ALTER TABLE workflow_runs
    DROP CONSTRAINT workflow_runs_status_check,
    DROP CONSTRAINT workflow_runs_review_state_check;

ALTER TABLE workflow_runs
    ADD CONSTRAINT workflow_runs_status_check
        CHECK (status IN (
            'pending', 'running', 'needs_input', 'paused', 'stopped', 'succeeded', 'failed'
        )),
    ADD COLUMN input jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN task_title text,
    ADD COLUMN task_phase text,
    ADD COLUMN task_summary text,
    ADD COLUMN task_question text,
    ADD COLUMN task_question_requested_at timestamptz,
    ADD COLUMN task_turn_number integer NOT NULL DEFAULT 0 CHECK (task_turn_number >= 0),
    ADD COLUMN task_control text CHECK (task_control IN ('pause', 'stop')),
    ADD COLUMN task_result text,
    ADD COLUMN task_diff jsonb,
    ADD COLUMN task_has_changes boolean;

ALTER TABLE workflow_runs
    ADD CONSTRAINT workflow_runs_review_state_check CHECK (
        (review_decision IS NULL AND reviewed_at IS NULL)
        OR
        (
            (review_required OR executor = 'project.task')
            AND review_decision = 'approved'
            AND reviewed_at IS NOT NULL
        )
    );

CREATE UNIQUE INDEX one_active_project_task
ON workflow_runs (project_id)
WHERE executor = 'project.task'
  AND status IN ('pending', 'running', 'needs_input', 'paused');

CREATE TABLE project_task_entries (
    id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
    request_id uuid,
    kind text NOT NULL
        CHECK (kind IN ('instruction', 'direction', 'answer', 'message', 'event', 'question')),
    source text NOT NULL CHECK (source IN ('founder', 'codex', 'tin')),
    content text NOT NULL CHECK (char_length(content) BETWEEN 1 AND 32000),
    author_clerk_user_id text
        CHECK (author_clerk_user_id ~ '^user_[A-Za-z0-9]+$'),
    delivered_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        (source = 'founder' AND author_clerk_user_id IS NOT NULL)
        OR (source IN ('codex', 'tin') AND author_clerk_user_id IS NULL)
    )
);

CREATE UNIQUE INDEX project_task_entries_request_idx
ON project_task_entries (run_id, request_id)
WHERE request_id IS NOT NULL;

CREATE INDEX project_task_entries_run_created_idx
ON project_task_entries (run_id, created_at, id);
