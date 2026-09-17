ALTER TABLE projects
    ADD COLUMN memory_commit_sha text,
    ADD COLUMN memory_index_path text,
    ADD COLUMN memory_index text,
    ADD COLUMN memory_updated_at timestamptz;

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
    '00000000-0000-4000-8000-000000000002',
    'project.memory',
    'Garden project memory',
    'Consolidate durable project outputs into the project wiki.',
    'project.memory',
    'registry/workflows',
    'workflows/project.memory.json',
    '1.0.0',
    '{
      "key": "project.memory",
      "version": "1.0.0",
      "title": "Garden project memory",
      "description": "Consolidate durable project outputs into the project wiki.",
      "executor": "project.memory",
      "input_schema": {
        "type": "object",
        "additionalProperties": false,
        "properties": {"project_id": {"type": "string", "format": "uuid"}},
        "required": ["project_id"]
      }
    }'::jsonb
)
ON CONFLICT (id) DO NOTHING;
