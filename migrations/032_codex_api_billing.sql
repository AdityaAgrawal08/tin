-- Add API request metering without changing existing OAuth/native budgets.
ALTER TABLE billing_operations DROP CONSTRAINT billing_operations_kind_check;
ALTER TABLE billing_operations ADD CONSTRAINT billing_operations_kind_check
    CHECK (kind IN ('native_model', 'isolated_codex', 'sandbox', 'tool', 'codex_api'));
