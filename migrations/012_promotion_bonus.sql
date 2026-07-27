-- A DEGIRO "Verrekening Promotie" is a credited bonus, not an unprocessed
-- cash event. SQLite cannot extend a CHECK constraint in place, so rebuild
-- this small table with the additional, valid ``bonus`` event type first.
PRAGMA foreign_keys=OFF;

ALTER TABLE cash_events RENAME TO cash_events_v12;

CREATE TABLE cash_events (
    id            INTEGER PRIMARY KEY,
    account_id    INTEGER NOT NULL REFERENCES accounts(id),
    instrument_id INTEGER REFERENCES instruments(id),
    ts            TEXT    NOT NULL,
    type          TEXT    NOT NULL CHECK(type IN (
                      'dividend','dividend_tax','fee','deposit',
                      'withdrawal','interest','bonus','other')),
    amount_eur    TEXT    NOT NULL,
    description   TEXT,
    dedup_hash    TEXT    UNIQUE
);

INSERT INTO cash_events(id, account_id, instrument_id, ts, type, amount_eur, description, dedup_hash)
SELECT id, account_id, instrument_id, ts,
       CASE
           WHEN type = 'other' AND lower(description) LIKE '%verrekening promotie%' THEN 'bonus'
           ELSE type
       END,
       amount_eur, description, dedup_hash
FROM cash_events_v12;

DROP TABLE cash_events_v12;

PRAGMA foreign_keys=ON;
