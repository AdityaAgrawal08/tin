CREATE TABLE workspaces (
    id uuid PRIMARY KEY,
    name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 80),
    created_by_clerk_user_id text
        CHECK (
            created_by_clerk_user_id IS NULL
            OR created_by_clerk_user_id ~ '^user_[A-Za-z0-9]+$'
        ),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE workspace_memberships (
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    clerk_user_id text NOT NULL CHECK (clerk_user_id ~ '^user_[A-Za-z0-9]+$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, clerk_user_id)
);

CREATE INDEX workspace_memberships_user_idx
ON workspace_memberships (clerk_user_id, workspace_id);

ALTER TABLE projects
    ADD COLUMN workspace_id uuid,
    ADD COLUMN created_by_clerk_user_id text
        CHECK (
            created_by_clerk_user_id IS NULL
            OR created_by_clerk_user_id ~ '^user_[A-Za-z0-9]+$'
        ),
    ADD COLUMN creation_request_id uuid;

-- Historical projects have no trustworthy creator signal. Give each one an isolated workspace,
-- preserve project access exactly, and leave workspace administration for explicit assignment.
INSERT INTO workspaces (id, name)
SELECT md5('https://lite.tin.computer/projects/' || id::text || '/workspace')::uuid, name
FROM projects;

UPDATE projects
SET workspace_id = md5(
    'https://lite.tin.computer/projects/' || id::text || '/workspace'
)::uuid
WHERE workspace_id IS NULL;

ALTER TABLE projects
    ALTER COLUMN workspace_id SET NOT NULL,
    ADD CONSTRAINT projects_workspace_id_fkey
        FOREIGN KEY (workspace_id) REFERENCES workspaces(id);

CREATE INDEX projects_workspace_idx
ON projects (workspace_id, created_at, id);

CREATE UNIQUE INDEX projects_workspace_name_unique_idx
ON projects (workspace_id, lower(name));

CREATE UNIQUE INDEX projects_creation_request_unique_idx
ON projects (workspace_id, creation_request_id)
WHERE creation_request_id IS NOT NULL;
