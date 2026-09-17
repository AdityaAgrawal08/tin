CREATE TABLE outreach_campaigns (
    run_id uuid PRIMARY KEY REFERENCES workflow_runs(id) ON DELETE CASCADE,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    channel text NOT NULL CHECK (channel IN ('email')),
    integration_connection_id uuid
        REFERENCES integration_connections(id) ON DELETE SET NULL,
    external_account_id text NOT NULL,
    source_path text NOT NULL,
    source_commit_sha text NOT NULL CHECK (length(source_commit_sha) = 40),
    review_path text NOT NULL,
    review_commit_sha text NOT NULL CHECK (length(review_commit_sha) = 40),
    follow_up_delay_days integer CHECK (follow_up_delay_days BETWEEN 1 AND 30),
    send_interval_seconds integer NOT NULL CHECK (send_interval_seconds BETWEEN 1 AND 3600),
    daily_send_cap integer NOT NULL CHECK (daily_send_cap BETWEEN 1 AND 200),
    send_window_start time NOT NULL,
    send_window_end time NOT NULL,
    send_timezone text NOT NULL,
    status text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'approved', 'running', 'completed', 'failed', 'stopped')),
    recipient_count integer NOT NULL CHECK (recipient_count BETWEEN 1 AND 200),
    sent_count integer NOT NULL DEFAULT 0 CHECK (sent_count >= 0),
    replied_count integer NOT NULL DEFAULT 0 CHECK (replied_count >= 0),
    failed_count integer NOT NULL DEFAULT 0 CHECK (failed_count >= 0),
    approved_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, run_id),
    CHECK (send_window_start < send_window_end)
);

CREATE TABLE outreach_recipients (
    id uuid PRIMARY KEY,
    campaign_run_id uuid NOT NULL REFERENCES outreach_campaigns(run_id) ON DELETE CASCADE,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    contact_key text NOT NULL,
    address text NOT NULL,
    display_name text NOT NULL DEFAULT '',
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'initial_sent', 'replied', 'follow_up_sent', 'completed', 'failed')),
    provider_thread_id text,
    initial_sent_at timestamptz,
    reply_checked_at timestamptz,
    replied_at timestamptz,
    follow_up_sent_at timestamptz,
    error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (campaign_run_id, address),
    UNIQUE (campaign_run_id, contact_key)
);

CREATE TABLE outreach_deliveries (
    execution_key text PRIMARY KEY,
    campaign_run_id uuid NOT NULL REFERENCES outreach_campaigns(run_id) ON DELETE CASCADE,
    recipient_id uuid NOT NULL REFERENCES outreach_recipients(id) ON DELETE CASCADE,
    channel text NOT NULL CHECK (channel IN ('email')),
    step_key text NOT NULL CHECK (step_key IN ('initial', 'follow_up')),
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'started', 'sent', 'unknown', 'failed', 'skipped')),
    provider_message_id text,
    provider_request_id text,
    scheduled_for timestamptz,
    started_at timestamptz,
    sent_at timestamptz,
    error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (recipient_id, step_key)
);

CREATE INDEX outreach_campaigns_project_idx
    ON outreach_campaigns (project_id, created_at DESC);
CREATE INDEX outreach_recipients_status_idx
    ON outreach_recipients (campaign_run_id, status, created_at);
CREATE INDEX outreach_deliveries_status_idx
    ON outreach_deliveries (campaign_run_id, status, created_at);
