ALTER TABLE project_workflows
    ADD COLUMN settings_revision integer NOT NULL DEFAULT 1
        CHECK (settings_revision > 0);
