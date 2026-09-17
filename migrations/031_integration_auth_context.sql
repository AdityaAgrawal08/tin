-- A connect attempt may carry provider context that the callback needs but the provider does
-- not echo back, such as the GitHub installation chosen on the already-installed path.
ALTER TABLE integration_auth_attempts
    ADD COLUMN context jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(context) = 'object');
