-- A reviewed document's own heading, shown in place of its run-owned file name.
-- The artifact path and the pinned output contract are unchanged.
ALTER TABLE workflow_runs ADD COLUMN artifact_title text
    CHECK (artifact_title IS NULL OR char_length(artifact_title) BETWEEN 1 AND 160);
