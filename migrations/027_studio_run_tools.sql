-- Creative-studio run tools. A studio grant binds a sandbox to the switchboard's fal-backed
-- voice endpoint for one run. It has no project-owned integration connection: the credential
-- is Tin's, so connection_id is null exactly when the provider is tin.studio.
ALTER TABLE run_tool_grants ALTER COLUMN connection_id DROP NOT NULL;
ALTER TABLE run_tool_grants DROP CONSTRAINT run_tool_grants_provider_key_check;
ALTER TABLE run_tool_grants
    ADD CONSTRAINT run_tool_grants_provider_key_check
        CHECK (provider_key IN ('workspace.google', 'tin.studio'));
ALTER TABLE run_tool_grants
    ADD CONSTRAINT run_tool_grants_connection_matches_provider_check
        CHECK ((provider_key = 'tin.studio') = (connection_id IS NULL));
