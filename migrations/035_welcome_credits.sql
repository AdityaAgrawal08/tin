-- A workspace wallet need not opt its workflows into the billing pilot.
-- Existing, explicitly enrolled accounts retain their admission policy.
ALTER TABLE billing_accounts
    ADD COLUMN run_billing_enabled boolean NOT NULL DEFAULT true,
    ADD COLUMN welcome_remaining_nanos bigint NOT NULL DEFAULT 0
        CHECK (welcome_remaining_nanos >= 0);

ALTER TABLE billing_ledger DROP CONSTRAINT billing_ledger_kind_check;
ALTER TABLE billing_ledger ADD CONSTRAINT billing_ledger_kind_check
    CHECK (kind IN ('topup', 'charge', 'refund', 'dispute', 'adjustment', 'welcome_credit'));

-- One grant per Tin identity, not per session, project, workspace, or promotion version.
CREATE TABLE billing_welcome_grants (
    clerk_user_id text PRIMARY KEY REFERENCES tin_users(clerk_user_id),
    workspace_id uuid NOT NULL REFERENCES billing_accounts(workspace_id),
    ledger_id bigint NOT NULL UNIQUE REFERENCES billing_ledger(id),
    amount_nanos bigint NOT NULL CHECK (amount_nanos = 10000000000),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER billing_welcome_grants_immutable BEFORE UPDATE OR DELETE ON billing_welcome_grants
    FOR EACH ROW EXECUTE FUNCTION billing_ledger_append_only();
