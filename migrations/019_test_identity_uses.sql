-- Every run that receives a Tin-owned test identity records which identity it used and whether
-- the run minted it or reused an earlier run's active account. Retries, status reports, and leak
-- checks resolve the identity by run through this table.
CREATE TABLE project_test_identity_uses (
    run_id uuid PRIMARY KEY REFERENCES workflow_runs(id) ON DELETE CASCADE,
    identity_id uuid NOT NULL REFERENCES project_test_identities(id) ON DELETE CASCADE,
    mode text NOT NULL CHECK (mode IN ('created', 'reused')),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX project_test_identity_uses_identity_idx
    ON project_test_identity_uses (identity_id, created_at DESC);

INSERT INTO project_test_identity_uses (run_id, identity_id, mode, created_at)
SELECT created_by_run_id, id, 'created', created_at
FROM project_test_identities
ON CONFLICT (run_id) DO NOTHING;
