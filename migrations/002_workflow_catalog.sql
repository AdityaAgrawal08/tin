CREATE TABLE workflows (
    id uuid PRIMARY KEY,
    project_id uuid REFERENCES projects(id),
    key text NOT NULL,
    title text NOT NULL,
    description text NOT NULL DEFAULT '',
    executor text NOT NULL,
    definition_repo_id text NOT NULL,
    definition_path text NOT NULL,
    current_commit_sha text,
    version_label text NOT NULL,
    definition jsonb NOT NULL DEFAULT '{}'::jsonb,
    forked_from_workflow_id uuid REFERENCES workflows(id),
    forked_from_commit_sha text,
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'paused', 'archived')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        (forked_from_workflow_id IS NULL AND forked_from_commit_sha IS NULL)
        OR
        (forked_from_workflow_id IS NOT NULL AND forked_from_commit_sha IS NOT NULL)
    )
);

CREATE UNIQUE INDEX one_registry_workflow_key
ON workflows (key)
WHERE project_id IS NULL;

CREATE UNIQUE INDEX one_project_workflow_key
ON workflows (project_id, key)
WHERE project_id IS NOT NULL;

INSERT INTO workflows (
    id,
    key,
    title,
    description,
    executor,
    definition_repo_id,
    definition_path,
    version_label,
    definition
)
VALUES (
    '00000000-0000-4000-8000-000000000001',
    'content.design_md',
    'Generate project design',
    'Analyze a project repository and publish its DESIGN.md.',
    'content.design_md',
    'registry/workflows',
    'workflows/content.design_md.json',
    '1.0.0',
    '{
      "key": "content.design_md",
      "version": "1.0.0",
      "title": "Generate project design",
      "description": "Analyze a project repository and publish its DESIGN.md.",
      "executor": "content.design_md",
      "input_schema": {
        "type": "object",
        "additionalProperties": false,
        "properties": {"project_id": {"type": "string", "format": "uuid"}},
        "required": ["project_id"]
      }
    }'::jsonb
);

ALTER TABLE workflow_runs
    ADD COLUMN workflow_id uuid,
    ADD COLUMN definition_commit_sha text,
    ADD COLUMN lease_owner text,
    ADD COLUMN fencing_token bigint,
    ADD COLUMN lease_active boolean NOT NULL DEFAULT false,
    ADD COLUMN lease_released_at timestamptz;

UPDATE workflow_runs
SET workflow_id = '00000000-0000-4000-8000-000000000001'
WHERE workflow_id IS NULL;

UPDATE workflow_runs AS runs
SET lease_owner = leases.lease_owner,
    fencing_token = leases.fencing_token,
    lease_active = leases.active,
    lease_released_at = leases.released_at
FROM session_leases AS leases
WHERE runs.project_id = leases.project_id
  AND runs.thread_id = leases.thread_id
  AND runs.generation = leases.generation;

CREATE SEQUENCE workflow_run_fencing_tokens;

UPDATE workflow_runs
SET fencing_token = nextval('workflow_run_fencing_tokens')
WHERE fencing_token IS NULL;

SELECT setval(
    'workflow_run_fencing_tokens',
    COALESCE((SELECT MAX(fencing_token) FROM workflow_runs), 0) + 1,
    false
);

ALTER TABLE workflow_runs
    ALTER COLUMN workflow_id SET NOT NULL,
    ALTER COLUMN fencing_token SET NOT NULL,
    ALTER COLUMN fencing_token SET DEFAULT nextval('workflow_run_fencing_tokens'),
    ADD CONSTRAINT workflow_runs_workflow_id_fkey
        FOREIGN KEY (workflow_id) REFERENCES workflows(id);

ALTER SEQUENCE workflow_run_fencing_tokens OWNED BY workflow_runs.fencing_token;

ALTER TABLE workflow_runs
    DROP CONSTRAINT workflow_runs_workflow_name_check;

ALTER TABLE workflow_runs
    RENAME COLUMN workflow_name TO executor;

CREATE UNIQUE INDEX one_active_workflow_run_lease
ON workflow_runs (project_id, thread_id)
WHERE lease_active;

DROP TABLE session_leases;

ALTER TABLE step_executions RENAME TO effect_receipts;
ALTER TABLE effect_receipts
    RENAME CONSTRAINT step_executions_pkey TO effect_receipts_pkey;
ALTER TABLE effect_receipts
    RENAME CONSTRAINT step_executions_status_check TO effect_receipts_status_check;

ALTER TABLE run_events RENAME TO activity_events;
ALTER TABLE activity_events
    ADD COLUMN project_id uuid,
    ADD COLUMN summary text,
    ADD COLUMN audience text NOT NULL DEFAULT 'internal'
        CHECK (audience IN ('internal', 'product')),
    ADD COLUMN dedupe_key text;

UPDATE activity_events AS events
SET project_id = runs.project_id
FROM workflow_runs AS runs
WHERE events.run_id = runs.id
  AND events.project_id IS NULL;

ALTER TABLE activity_events
    ALTER COLUMN project_id SET NOT NULL,
    ALTER COLUMN run_id DROP NOT NULL,
    ADD CONSTRAINT activity_events_project_id_fkey
        FOREIGN KEY (project_id) REFERENCES projects(id);

ALTER INDEX run_events_run_idx RENAME TO activity_events_run_idx;

CREATE INDEX activity_events_project_idx
ON activity_events (project_id, id);

CREATE UNIQUE INDEX activity_events_dedupe_key_idx
ON activity_events (dedupe_key)
WHERE dedupe_key IS NOT NULL;
