-- Locally cached Logo.dev assets. Successful and missing lookups are both
-- remembered, so tables do not trigger a remote request on every render.
CREATE TABLE IF NOT EXISTS logo_cache (
    mode       TEXT NOT NULL CHECK(mode IN ('isin', 'ticker', 'name')),
    value      TEXT NOT NULL,
    status     INTEGER NOT NULL CHECK(status IN (200, 404)),
    filename   TEXT,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (mode, value)
);
