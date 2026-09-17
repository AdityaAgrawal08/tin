-- Write-only run credentials. Never part of workflow inputs or saved configurations.
CREATE TABLE run_payment_cards (
    run_id uuid PRIMARY KEY REFERENCES workflow_runs(id) ON DELETE CASCADE,
    ciphertext bytea NOT NULL,
    encryption_key_id text NOT NULL
);

CREATE FUNCTION discard_run_payment_card() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status IN ('succeeded', 'failed', 'stopped', 'superseded') THEN
        DELETE FROM run_payment_cards WHERE run_id = NEW.id;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER discard_run_payment_card_on_completion
AFTER UPDATE OF status ON workflow_runs
FOR EACH ROW EXECUTE FUNCTION discard_run_payment_card();
