-- Migration 002: add dedup_hash to transactions
-- This allows reliable deduplication of account CSV rows that have identical
-- (account_id, ts, quantity, price) but different Saldo values — e.g. two
-- purchases of the same stock at the same price within the same minute.
-- The hash is SHA-256 of the full raw CSV row (including Saldo column).

ALTER TABLE transactions ADD COLUMN dedup_hash TEXT;
CREATE INDEX IF NOT EXISTS idx_transactions_dedup_hash ON transactions(dedup_hash);
