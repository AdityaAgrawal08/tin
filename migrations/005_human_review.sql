ALTER TABLE workflow_runs
    DROP CONSTRAINT workflow_runs_status_check;

ALTER TABLE workflow_runs
    ADD CONSTRAINT workflow_runs_status_check
        CHECK (status IN ('pending', 'running', 'needs_input', 'succeeded', 'failed')),
    ADD COLUMN review_required boolean NOT NULL DEFAULT false,
    ADD COLUMN review_decision text
        CHECK (review_decision IN ('approved')),
    ADD COLUMN review_requested_at timestamptz,
    ADD COLUMN reviewed_at timestamptz;

ALTER TABLE workflow_runs
    ADD CONSTRAINT workflow_runs_review_state_check CHECK (
        (review_decision IS NULL AND reviewed_at IS NULL)
        OR
        (review_required AND review_decision = 'approved' AND reviewed_at IS NOT NULL)
    );
