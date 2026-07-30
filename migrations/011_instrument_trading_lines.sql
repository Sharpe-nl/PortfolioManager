-- Keep separate trade lines for the same ISIN when they were traded in a
-- different currency.  A DEGIRO Account.csv has no reliable exchange column,
-- but its transaction currency does distinguish the common EUR/USD/GBP
-- listings.  The exchange can still be selected manually per line later.

PRAGMA foreign_keys=OFF;

CREATE TEMP TABLE instrument_currency_lines AS
SELECT instrument_id AS old_id,
       local_currency AS trading_currency,
       ROW_NUMBER() OVER (
           PARTITION BY instrument_id
           ORDER BY CASE WHEN local_currency = i.currency THEN 0 ELSE 1 END,
                    local_currency
       ) AS line_number
FROM transactions
JOIN instruments i ON i.id = transactions.instrument_id
GROUP BY instrument_id, local_currency;

CREATE TEMP TABLE instrument_currency_map (
    old_id INTEGER NOT NULL,
    trading_currency TEXT NOT NULL,
    new_id INTEGER NOT NULL,
    PRIMARY KEY (old_id, trading_currency)
);

INSERT INTO instrument_currency_map(old_id, trading_currency, new_id)
SELECT old_id, trading_currency, old_id
FROM instrument_currency_lines
WHERE line_number = 1;

INSERT INTO instrument_currency_map(old_id, trading_currency, new_id)
SELECT old_id,
       trading_currency,
       (SELECT COALESCE(MAX(id), 0) FROM instruments)
           + ROW_NUMBER() OVER (ORDER BY old_id, trading_currency)
FROM instrument_currency_lines
WHERE line_number > 1;

CREATE TABLE instruments_v11 (
    id               INTEGER PRIMARY KEY,
    isin             TEXT,
    name             TEXT NOT NULL,
    symbol           TEXT,
    exchange         TEXT,
    currency         TEXT,
    trading_currency TEXT,
    asset_type       TEXT DEFAULT 'other'
                     CHECK(asset_type IN ('stock','etf','fund','bond','cash','other')),
    sector           TEXT,
    region           TEXT
);

-- Preserve the existing instrument IDs for the first trading currency so all
-- existing price, logo and allocation data remains available.
INSERT INTO instruments_v11(
    id, isin, name, symbol, exchange, currency, trading_currency,
    asset_type, sector, region
)
SELECT i.id, i.isin, i.name, i.symbol, i.exchange, i.currency,
       m.trading_currency, i.asset_type, i.sector, i.region
FROM instruments i
LEFT JOIN instrument_currency_map m
    ON m.old_id = i.id AND m.new_id = i.id;

-- Additional currencies receive their own clean quote mapping. Their ticker
-- is intentionally empty: an old ticker may point at the wrong listing.
INSERT INTO instruments_v11(
    id, isin, name, symbol, exchange, currency, trading_currency,
    asset_type, sector, region
)
SELECT m.new_id, i.isin, i.name, NULL, NULL, NULL, m.trading_currency,
       i.asset_type, i.sector, i.region
FROM instrument_currency_map m
JOIN instruments i ON i.id = m.old_id
WHERE m.new_id != m.old_id;

UPDATE transactions
SET instrument_id = (
    SELECT m.new_id
    FROM instrument_currency_map m
    WHERE m.old_id = transactions.instrument_id
      AND m.trading_currency = transactions.local_currency
)
WHERE EXISTS (
    SELECT 1 FROM instrument_currency_map m
    WHERE m.old_id = transactions.instrument_id
      AND m.trading_currency = transactions.local_currency
);

DROP TABLE instruments;
ALTER TABLE instruments_v11 RENAME TO instruments;

CREATE UNIQUE INDEX uq_instruments_isin_trading_currency
    ON instruments(isin, trading_currency)
    WHERE isin IS NOT NULL AND trading_currency IS NOT NULL;
CREATE INDEX idx_instruments_isin ON instruments(isin);

DROP TABLE instrument_currency_map;
DROP TABLE instrument_currency_lines;

PRAGMA foreign_keys=ON;
