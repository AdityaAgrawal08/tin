CREATE TABLE outreach_campaign_revisions (
    id uuid PRIMARY KEY,
    campaign_run_id uuid NOT NULL REFERENCES outreach_campaigns(run_id) ON DELETE CASCADE,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    request_id uuid NOT NULL,
    revision_number integer NOT NULL CHECK (revision_number > 0),
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'discarded')),
    previous_follow_up_body text NOT NULL CHECK (length(previous_follow_up_body) BETWEEN 1 AND 20000),
    follow_up_body text NOT NULL CHECK (length(follow_up_body) BETWEEN 1 AND 20000),
    review_path text NOT NULL,
    review_commit_sha text CHECK (review_commit_sha IS NULL OR length(review_commit_sha) = 40),
    requested_by_clerk_user_id text NOT NULL,
    reviewed_by_clerk_user_id text,
    requested_at timestamptz NOT NULL DEFAULT now(),
    reviewed_at timestamptz,
    UNIQUE (project_id, request_id),
    UNIQUE (campaign_run_id, revision_number)
);

CREATE UNIQUE INDEX outreach_campaign_one_pending_revision_idx
    ON outreach_campaign_revisions (campaign_run_id)
    WHERE status = 'pending';

CREATE INDEX outreach_campaign_revisions_project_idx
    ON outreach_campaign_revisions (project_id, requested_at DESC);
