-- Personal list preference only: hiding never removes membership or pauses work.
ALTER TABLE project_memberships
    ADD COLUMN hidden boolean NOT NULL DEFAULT false;
