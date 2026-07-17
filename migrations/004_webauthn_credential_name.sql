-- Migration 004: allow naming individual YubiKeys, so multiple keys
-- (e.g. a primary + a backup) can be told apart when managing them.

ALTER TABLE webauthn_credentials ADD COLUMN name TEXT;
