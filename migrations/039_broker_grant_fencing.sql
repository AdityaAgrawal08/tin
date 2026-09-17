-- Old grants have no isolation/lease proof and deliberately remain unusable.
-- Do not backfill them from a run whose sandbox or generation may have changed.
ALTER TABLE broker_grants
    ADD COLUMN project_id uuid,
    ADD COLUMN generation bigint,
    ADD COLUMN fencing_token bigint;
