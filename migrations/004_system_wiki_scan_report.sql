ALTER TABLE workflow_runs
    ADD COLUMN system_wiki_commit_sha text;

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
    '00000000-0000-4000-8000-000000000003',
    'scan.report',
    'Scan project',
    'Review durable project knowledge against the system scanning guide and publish SCAN.md.',
    'scan.report',
    'registry/workflows',
    'workflows/scan.report.json',
    '1.0.0',
    '{
      "key": "scan.report",
      "version": "1.0.0",
      "title": "Scan project",
      "description": "Review durable project knowledge against the system scanning guide and publish SCAN.md.",
      "executor": "scan.report",
      "input_schema": {
        "type": "object",
        "additionalProperties": false,
        "properties": {"project_id": {"type": "string", "format": "uuid"}},
        "required": ["project_id"]
      }
    }'::jsonb
)
ON CONFLICT (id) DO NOTHING;
