-- Prerequisite evidence pinned at admission. Satisfaction itself is derived at call time from
-- succeeded runs, the project-state HEAD and active test identities; this column records what
-- the gate resolved for one run so its lineage stays answerable.
ALTER TABLE workflow_runs
    ADD COLUMN prerequisite_evidence jsonb
        CHECK (prerequisite_evidence IS NULL OR jsonb_typeof(prerequisite_evidence) = 'object');

-- Prerequisite gating and listing readiness look up a project's succeeded, published runs by
-- workflow identity. Codex procedures share one executor, so executor is not selective.
CREATE INDEX workflow_runs_project_succeeded_idx
    ON workflow_runs (project_id, workflow_id, finished_at DESC NULLS LAST, id DESC)
    WHERE status = 'succeeded' AND canonical_commit_sha IS NOT NULL;
