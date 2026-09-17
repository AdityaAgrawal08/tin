ALTER TABLE projects
    ADD COLUMN timezone text NOT NULL DEFAULT 'UTC'
        CHECK (char_length(timezone) BETWEEN 1 AND 100);

ALTER TABLE project_workflows
    ADD COLUMN skip_scheduled_for timestamptz;

ALTER TABLE workflow_runs
    DROP CONSTRAINT workflow_runs_trigger_source_check,
    ADD CONSTRAINT workflow_runs_trigger_source_check
        CHECK (trigger_source IN ('manual', 'chat', 'mcp', 'schedule', 'api')),
    ADD COLUMN trigger_client text
        CHECK (trigger_client IS NULL OR trigger_client IN ('claude_code', 'codex', 'api')),
    ADD COLUMN started_by_oauth_client_id text,
    ADD COLUMN retry_of_run_id uuid REFERENCES workflow_runs(id),
    ADD COLUMN progress_mode text NOT NULL DEFAULT 'indeterminate'
        CHECK (progress_mode IN ('steps', 'units', 'indeterminate')),
    ADD COLUMN progress_step text,
    ADD COLUMN progress_current integer CHECK (progress_current IS NULL OR progress_current >= 0),
    ADD COLUMN progress_total integer CHECK (progress_total IS NULL OR progress_total > 0),
    ADD COLUMN progress_percent smallint
        CHECK (progress_percent IS NULL OR progress_percent BETWEEN 0 AND 100),
    ADD COLUMN progress_summary text
        CHECK (progress_summary IS NULL OR char_length(progress_summary) <= 240),
    ADD COLUMN progress_updated_at timestamptz,
    ADD COLUMN heartbeat_at timestamptz,
    ADD COLUMN result_summary text
        CHECK (result_summary IS NULL OR char_length(result_summary) <= 160),
    ADD CONSTRAINT workflow_runs_progress_shape CHECK (
        (progress_current IS NULL AND progress_total IS NULL)
        OR (progress_current IS NOT NULL AND progress_total IS NOT NULL
            AND progress_current <= progress_total)
    );

CREATE INDEX workflow_runs_project_active_idx
ON workflow_runs (project_id, created_at DESC, id DESC)
WHERE status IN ('pending', 'running', 'needs_input', 'paused');

CREATE INDEX workflow_runs_retry_idx
ON workflow_runs (retry_of_run_id)
WHERE retry_of_run_id IS NOT NULL;
