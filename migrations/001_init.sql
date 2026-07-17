-- Migration 001: initial schema
-- All money stored as TEXT decimal (never REAL/FLOAT).
-- Run via db.run_migrations() on app startup.

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS accounts (
    id       INTEGER PRIMARY KEY,
    name     TEXT    NOT NULL,
    type     TEXT    NOT NULL CHECK(type IN ('broker','pension','savings','other')),
    currency TEXT    NOT NULL DEFAULT 'EUR'
);

CREATE TABLE IF NOT EXISTS instruments (
    id         INTEGER PRIMARY KEY,
    isin       TEXT UNIQUE,
    name       TEXT NOT NULL,
    symbol     TEXT,              -- yfinance ticker, NULL until mapped
    exchange   TEXT,
    currency   TEXT,
    asset_type TEXT DEFAULT 'other'
                   CHECK(asset_type IN ('stock','etf','fund','bond','cash','other')),
    sector     TEXT,              -- manual override wins
    region     TEXT
);

CREATE TABLE IF NOT EXISTS transactions (
    id             INTEGER PRIMARY KEY,
    account_id     INTEGER NOT NULL REFERENCES accounts(id),
    instrument_id  INTEGER NOT NULL REFERENCES instruments(id),
    ts             TEXT    NOT NULL,   -- ISO 8601
    quantity       TEXT    NOT NULL,   -- Decimal as text; negative = sell
    price          TEXT    NOT NULL,   -- per unit, local currency
    local_currency TEXT    NOT NULL,
    fx_rate        TEXT,               -- local → EUR
    value_eur      TEXT    NOT NULL,   -- total in EUR (negative = money out)
    fees_eur       TEXT    NOT NULL DEFAULT '0',
    order_id       TEXT,               -- DeGiro order ID
    source         TEXT    NOT NULL,   -- 'degiro_csv' | 'manual'
    UNIQUE(account_id, order_id, ts, quantity, price)
);

CREATE TABLE IF NOT EXISTS cash_events (
    id            INTEGER PRIMARY KEY,
    account_id    INTEGER NOT NULL REFERENCES accounts(id),
    instrument_id INTEGER REFERENCES instruments(id),
    ts            TEXT    NOT NULL,
    type          TEXT    NOT NULL CHECK(type IN (
                      'dividend','dividend_tax','fee','deposit',
                      'withdrawal','interest','other')),
    amount_eur    TEXT    NOT NULL,
    description   TEXT,
    dedup_hash    TEXT    UNIQUE       -- sha256 of raw CSV row
);

CREATE TABLE IF NOT EXISTS prices (
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    date          TEXT    NOT NULL,
    close         TEXT    NOT NULL,
    currency      TEXT    NOT NULL,
    fetched_at    TEXT    NOT NULL,
    PRIMARY KEY (instrument_id, date)
);

CREATE TABLE IF NOT EXISTS balance_snapshots (
    id          INTEGER PRIMARY KEY,
    account_id  INTEGER NOT NULL REFERENCES accounts(id),
    date        TEXT    NOT NULL,
    balance_eur TEXT    NOT NULL,
    UNIQUE(account_id, date)
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- WebAuthn/FIDO2 credentials (YubiKey)
CREATE TABLE IF NOT EXISTS webauthn_credentials (
    id            INTEGER PRIMARY KEY,
    credential_id BLOB    NOT NULL UNIQUE,
    public_key    BLOB    NOT NULL,
    sign_count    INTEGER NOT NULL DEFAULT 0,
    user_handle   BLOB    NOT NULL,
    transports    TEXT,              -- JSON array or NULL
    created_at    TEXT    NOT NULL
);

-- Import audit log
CREATE TABLE IF NOT EXISTS import_log (
    id             INTEGER PRIMARY KEY,
    account_id     INTEGER REFERENCES accounts(id),
    filename       TEXT,
    file_type      TEXT,
    imported_at    TEXT    NOT NULL,
    rows_imported  INTEGER NOT NULL DEFAULT 0,
    rows_skipped   INTEGER NOT NULL DEFAULT 0,
    rows_error     INTEGER NOT NULL DEFAULT 0,
    errors         TEXT               -- JSON array of error strings
);

-- Temporary staging area for import preview/confirm flow
CREATE TABLE IF NOT EXISTS import_staging (
    id          INTEGER PRIMARY KEY,
    session_key TEXT    NOT NULL,
    row_type    TEXT    NOT NULL,   -- 'transaction' | 'cash_event' | 'skip'
    row_json    TEXT    NOT NULL,   -- JSON of the parsed (but not yet committed) row
    status      TEXT    NOT NULL,   -- 'new' | 'duplicate' | 'error' | 'informational'
    error_msg   TEXT,
    created_at  TEXT    NOT NULL    -- for TTL-based cleanup
);

CREATE INDEX IF NOT EXISTS idx_staging_session ON import_staging(session_key);
CREATE INDEX IF NOT EXISTS idx_staging_created ON import_staging(created_at);
