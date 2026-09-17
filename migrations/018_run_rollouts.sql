CREATE TABLE run_rollouts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
    generation bigint NOT NULL CHECK (generation > 0),
    execution_key text NOT NULL CHECK (length(execution_key) BETWEEN 1 AND 200),
    activity_attempt integer NOT NULL CHECK (activity_attempt > 0),
    stage text NOT NULL CHECK (stage IN ('codex', 'codex_procedure', 'project_task')),
    sandbox_id text NOT NULL CHECK (length(sandbox_id) BETWEEN 1 AND 128),
    thread_id text CHECK (thread_id IS NULL OR length(thread_id) <= 64),
    filename text NOT NULL CHECK (filename ~ '^rollout-[A-Za-z0-9-]+\.jsonl$'),
    content_gzip bytea NOT NULL,
    size_bytes integer NOT NULL CHECK (size_bytes >= 0),
    stored_bytes integer NOT NULL CHECK (stored_bytes >= 0),
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    truncated boolean NOT NULL DEFAULT false,
    redactions integer NOT NULL DEFAULT 0 CHECK (redactions >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, generation, filename)
);

CREATE INDEX run_rollouts_run_idx ON run_rollouts (run_id, id);
