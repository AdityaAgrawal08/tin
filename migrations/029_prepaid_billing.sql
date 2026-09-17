-- Opt-in test billing. Existing workspaces and historical runs are not enrolled.
CREATE TABLE billing_accounts (
    workspace_id uuid PRIMARY KEY REFERENCES workspaces(id),
    mode text NOT NULL CHECK (mode = 'test'),
    admin_clerk_user_id text NOT NULL,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended')),
    balance_nanos bigint NOT NULL DEFAULT 0,
    reserved_nanos bigint NOT NULL DEFAULT 0 CHECK (reserved_nanos >= 0),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE billing_project_policies (
    project_id uuid PRIMARY KEY REFERENCES projects(id),
    workspace_id uuid NOT NULL REFERENCES billing_accounts(workspace_id),
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    per_run_nanos bigint NOT NULL CHECK (per_run_nanos > 0),
    monthly_nanos bigint NOT NULL CHECK (monthly_nanos > 0),
    concurrency integer NOT NULL CHECK (concurrency BETWEEN 1 AND 20),
    schedule_max_nanos bigint CHECK (schedule_max_nanos > 0),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE billing_quotes (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id),
    actor_clerk_user_id text NOT NULL,
    workflow_id uuid NOT NULL REFERENCES workflows(id),
    project_workflow_id uuid REFERENCES project_workflows(id),
    definition_revision text NOT NULL,
    input_sha256 text NOT NULL,
    terms jsonb NOT NULL,
    maximum_nanos bigint NOT NULL CHECK (maximum_nanos > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);

CREATE TABLE billing_run_budgets (
    run_id uuid PRIMARY KEY REFERENCES workflow_runs(id),
    root_run_id uuid NOT NULL REFERENCES workflow_runs(id),
    workspace_id uuid NOT NULL REFERENCES billing_accounts(workspace_id),
    project_id uuid NOT NULL REFERENCES projects(id),
    quote_id uuid UNIQUE REFERENCES billing_quotes(id),
    terms jsonb NOT NULL,
    maximum_nanos bigint NOT NULL CHECK (maximum_nanos > 0),
    committed_nanos bigint NOT NULL DEFAULT 0 CHECK (committed_nanos >= 0),
    status text NOT NULL DEFAULT 'reserved'
        CHECK (status IN ('reserved', 'pending', 'settled')),
    charged_nanos bigint CHECK (charged_nanos >= 0 AND charged_nanos <= maximum_nanos),
    period_start date NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    settled_at timestamptz,
    reconcile_by timestamptz NOT NULL DEFAULT now() + interval '24 hours'
);
CREATE INDEX billing_budget_root_idx ON billing_run_budgets(root_run_id);
CREATE INDEX billing_budget_project_period_idx
    ON billing_run_budgets(project_id, period_start);

CREATE TABLE billing_operations (
    id text PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES billing_run_budgets(run_id),
    root_run_id uuid NOT NULL REFERENCES workflow_runs(id),
    kind text NOT NULL CHECK (kind IN ('native_model', 'isolated_codex', 'sandbox', 'tool')),
    maximum_nanos bigint NOT NULL CHECK (maximum_nanos >= 0),
    observed_nanos bigint CHECK (observed_nanos >= 0),
    observation jsonb,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'observed', 'absorbed')),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX billing_operation_root_idx ON billing_operations(root_run_id);

CREATE TABLE billing_ledger (
    id bigserial PRIMARY KEY,
    workspace_id uuid NOT NULL REFERENCES billing_accounts(workspace_id),
    project_id uuid REFERENCES projects(id),
    run_id uuid REFERENCES workflow_runs(id),
    event_key text NOT NULL UNIQUE,
    kind text NOT NULL CHECK (kind IN ('topup', 'charge', 'refund', 'dispute', 'adjustment')),
    amount_nanos bigint NOT NULL,
    balance_after_nanos bigint NOT NULL,
    reference text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX billing_ledger_workspace_idx ON billing_ledger(workspace_id, id DESC);

-- Corrections append compensating entries; a charged history is never rewritten.
CREATE FUNCTION billing_ledger_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'billing ledger is append-only';
END;
$$;
CREATE TRIGGER billing_ledger_immutable BEFORE UPDATE OR DELETE ON billing_ledger
    FOR EACH ROW EXECUTE FUNCTION billing_ledger_append_only();

CREATE TABLE billing_payments (
    id uuid PRIMARY KEY,
    workspace_id uuid NOT NULL REFERENCES billing_accounts(workspace_id),
    actor_clerk_user_id text NOT NULL,
    request_id uuid NOT NULL,
    amount_cents integer NOT NULL CHECK (amount_cents BETWEEN 1000 AND 100000),
    stripe_session_id text UNIQUE,
    stripe_payment_intent_id text UNIQUE,
    checkout_url text,
    invoice_id text,
    invoice_url text,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'paid', 'expired')),
    refunded_cents integer NOT NULL DEFAULT 0 CHECK (refunded_cents >= 0),
    consumed_cents integer NOT NULL DEFAULT 0 CHECK (consumed_cents >= 0),
    refund_reserved_cents integer NOT NULL DEFAULT 0 CHECK (refund_reserved_cents >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, request_id),
    CHECK (refunded_cents + refund_reserved_cents <= amount_cents)
);

CREATE TABLE billing_refunds (
    id uuid PRIMARY KEY,
    payment_id uuid NOT NULL REFERENCES billing_payments(id),
    request_id uuid NOT NULL,
    actor_clerk_user_id text NOT NULL,
    amount_cents integer NOT NULL CHECK (amount_cents > 0),
    stripe_refund_id text UNIQUE,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'succeeded', 'failed')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (payment_id, request_id)
);

CREATE TABLE billing_payment_events (
    stripe_event_id text PRIMARY KEY,
    event_type text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE billing_disputes (
    stripe_dispute_id text PRIMARY KEY,
    payment_id uuid NOT NULL REFERENCES billing_payments(id),
    amount_cents integer NOT NULL CHECK (amount_cents > 0),
    status text NOT NULL CHECK (status IN ('open', 'won', 'lost'))
);
