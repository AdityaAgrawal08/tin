-- Migration 021 could not infer one historical owner, but every existing project member had
-- already been granted the platform's flat administrative access. Preserve that contract at the
-- new workspace boundary for historical data. Future project invitations remain project-scoped.
INSERT INTO workspace_memberships (workspace_id, clerk_user_id)
SELECT DISTINCT projects.workspace_id, project_memberships.clerk_user_id
FROM projects
JOIN project_memberships
  ON project_memberships.project_id = projects.id
ON CONFLICT (workspace_id, clerk_user_id) DO NOTHING;
