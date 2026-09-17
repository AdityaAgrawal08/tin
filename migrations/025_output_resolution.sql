-- A saved-output decision is separate from the original run's outcome.
-- Content stays in code.storage; the effect receipt owns request/retry provenance.
ALTER TABLE workflow_runs ADD COLUMN IF NOT EXISTS output_resolution jsonb;
ALTER TABLE workflow_runs ADD CONSTRAINT workflow_runs_output_resolution_object
    CHECK (output_resolution IS NULL OR jsonb_typeof(output_resolution) = 'object');
