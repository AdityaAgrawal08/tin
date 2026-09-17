-- Tin-owned phone numbers for test identities and the SMS they receive.
-- The number is receive-only: Tin never sends from it. One number is shared by every identity
-- until a pool is needed, so messages are keyed by the receiving number and time.
ALTER TABLE project_test_identities
    ADD COLUMN phone_number text
        CHECK (phone_number IS NULL OR phone_number ~ '^\+[1-9][0-9]{6,14}$');

CREATE TABLE test_identity_sms_messages (
    id uuid PRIMARY KEY,
    message_sid text NOT NULL UNIQUE CHECK (length(message_sid) BETWEEN 1 AND 64),
    to_number text NOT NULL CHECK (to_number ~ '^\+[1-9][0-9]{6,14}$'),
    from_number text NOT NULL CHECK (length(from_number) BETWEEN 1 AND 32),
    body text NOT NULL CHECK (length(body) <= 2000),
    received_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX test_identity_sms_messages_to_received_idx
    ON test_identity_sms_messages (to_number, received_at DESC);
