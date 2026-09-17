-- Availability of one validated procedure result is independent from run success.
-- Only immutable references and bounded facts belong here, never output bodies.
ALTER TABLE workflow_runs
    ADD COLUMN IF NOT EXISTS retained_output jsonb;

ALTER TABLE workflow_runs
    ADD CONSTRAINT workflow_runs_retained_output_object
    CHECK (retained_output IS NULL OR jsonb_typeof(retained_output) = 'object');
