-- The service grant authorizes only bindings in the run's pinned definition.
-- Individual connections remain project-owned and are checked on every call.
ALTER TABLE run_tool_grants DROP CONSTRAINT run_tool_grants_provider_key_check;
ALTER TABLE run_tool_grants ADD CONSTRAINT run_tool_grants_provider_key_check
    CHECK (provider_key IN ('workspace.google', 'tin.studio', 'tin.services'));
ALTER TABLE run_tool_grants DROP CONSTRAINT run_tool_grants_connection_matches_provider_check;
ALTER TABLE run_tool_grants ADD CONSTRAINT run_tool_grants_connection_matches_provider_check
    CHECK ((provider_key IN ('tin.studio', 'tin.services')) = (connection_id IS NULL));
