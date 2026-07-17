-- Migration 003: Replace the compound UNIQUE constraint on transactions with a
-- dedup_hash-based partial unique index.
--
-- Problem: UNIQUE(account_id, order_id, ts, quantity, price) incorrectly blocks
-- legitimate duplicate rows, e.g. two fills of the same order at the same
-- time and price (two lots of ASR @ 34,55 bought at 09:00 in a single order).
-- These rows look identical on (ts, qty, price) but have DIFFERENT running
-- balances (Saldo), so their SHA-256 dedup_hash values differ.
--
-- Fix: drop the compound UNIQUE and use dedup_hash for rows that have one.
-- Rows without a dedup_hash (manually entered, or imported before migration 002)
-- fall back to order_id-based uniqueness.

PRAGMA foreign_keys = OFF;

CREATE TABLE transactions_v3 (
    id             INTEGER PRIMARY KEY,
    account_id     INTEGER NOT NULL REFERENCES accounts(id),
    instrument_id  INTEGER NOT NULL REFERENCES instruments(id),
    ts             TEXT    NOT NULL,
    quantity       TEXT    NOT NULL,
    price          TEXT    NOT NULL,
    local_currency TEXT    NOT NULL,
    fx_rate        TEXT,
    value_eur      TEXT    NOT NULL,
    fees_eur       TEXT    NOT NULL DEFAULT '0',
    order_id       TEXT,
    source         TEXT    NOT NULL,
    dedup_hash     TEXT
);

INSERT INTO transactions_v3
    SELECT id, account_id, instrument_id, ts, quantity, price,
           local_currency, fx_rate, value_eur, fees_eur, order_id,
           source, dedup_hash
    FROM transactions;

DROP TABLE transactions;
ALTER TABLE transactions_v3 RENAME TO transactions;

PRAGMA foreign_keys = ON;

-- Primary dedup: hash of the full raw CSV row (includes Saldo / running balance).
-- Active for all rows imported via the CSV importers.
CREATE UNIQUE INDEX IF NOT EXISTS uq_transactions_dedup_hash
    ON transactions(dedup_hash)
    WHERE dedup_hash IS NOT NULL;

-- Fallback dedup for rows without a hash but with an order_id
-- (e.g. rows imported before migration 002, or manual entries).
CREATE UNIQUE INDEX IF NOT EXISTS uq_transactions_legacy
    ON transactions(account_id, order_id, ts, quantity, price)
    WHERE dedup_hash IS NULL AND order_id IS NOT NULL;

-- Retain the lookup index used by _check_transaction_dup.
CREATE INDEX IF NOT EXISTS idx_transactions_dedup_hash ON transactions(dedup_hash);
