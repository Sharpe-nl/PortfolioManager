-- Optional local username/password authentication. Passwords are stored only
-- as salted scrypt hashes; WebAuthn remains available alongside these users.
CREATE TABLE IF NOT EXISTS local_credentials (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL COLLATE NOCASE UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
