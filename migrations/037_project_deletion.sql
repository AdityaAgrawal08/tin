-- A deleted project keeps its row for billing history; deleted_at hides it from every gate.
ALTER TABLE projects
    ADD COLUMN deleted_at timestamptz,
    ADD COLUMN deleted_by_clerk_user_id text;

-- A deleted project's name may be reused inside its workspace.
DROP INDEX projects_workspace_name_unique_idx;
CREATE UNIQUE INDEX projects_workspace_name_unique_idx
ON projects (workspace_id, lower(name)) WHERE deleted_at IS NULL;
