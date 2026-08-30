-- A stock is one instrument per ISIN. Earlier currency-line imports could
-- create multiple stock rows when an old row had no trading currency or when
-- a cash event used a currency other than the listing currency.

PRAGMA foreign_keys=OFF;

-- Allow the canonical row to inherit a duplicate's trading currency before
-- that duplicate is removed.
DROP INDEX uq_instruments_isin_trading_currency;

CREATE TEMP TABLE duplicate_stock_instrument_map AS
SELECT duplicate.id AS old_id,
       (
           SELECT MIN(canonical.id)
           FROM instruments canonical
           WHERE canonical.isin = duplicate.isin
             AND canonical.asset_type = 'stock'
       ) AS keep_id
FROM instruments duplicate
WHERE duplicate.asset_type = 'stock'
  AND duplicate.isin IS NOT NULL
  AND duplicate.id != (
      SELECT MIN(canonical.id)
      FROM instruments canonical
      WHERE canonical.isin = duplicate.isin
        AND canonical.asset_type = 'stock'
  );

-- Preserve useful metadata when it only existed on a duplicate row.
UPDATE instruments AS keep
SET symbol = COALESCE(keep.symbol, (
        SELECT old.symbol FROM duplicate_stock_instrument_map map
        JOIN instruments old ON old.id = map.old_id
        WHERE map.keep_id = keep.id AND old.symbol IS NOT NULL LIMIT 1
    )),
    exchange = COALESCE(keep.exchange, (
        SELECT old.exchange FROM duplicate_stock_instrument_map map
        JOIN instruments old ON old.id = map.old_id
        WHERE map.keep_id = keep.id AND old.exchange IS NOT NULL LIMIT 1
    )),
    currency = COALESCE(keep.currency, (
        SELECT old.currency FROM duplicate_stock_instrument_map map
        JOIN instruments old ON old.id = map.old_id
        WHERE map.keep_id = keep.id AND old.currency IS NOT NULL LIMIT 1
    )),
    trading_currency = COALESCE(keep.trading_currency, (
        SELECT old.trading_currency FROM duplicate_stock_instrument_map map
        JOIN instruments old ON old.id = map.old_id
        WHERE map.keep_id = keep.id AND old.trading_currency IS NOT NULL LIMIT 1
    )),
    sector = COALESCE(keep.sector, (
        SELECT old.sector FROM duplicate_stock_instrument_map map
        JOIN instruments old ON old.id = map.old_id
        WHERE map.keep_id = keep.id AND old.sector IS NOT NULL LIMIT 1
    )),
    region = COALESCE(keep.region, (
        SELECT old.region FROM duplicate_stock_instrument_map map
        JOIN instruments old ON old.id = map.old_id
        WHERE map.keep_id = keep.id AND old.region IS NOT NULL LIMIT 1
    ))
WHERE keep.id IN (SELECT keep_id FROM duplicate_stock_instrument_map);

UPDATE transactions
SET instrument_id = (
    SELECT keep_id FROM duplicate_stock_instrument_map
    WHERE old_id = transactions.instrument_id
)
WHERE instrument_id IN (SELECT old_id FROM duplicate_stock_instrument_map);

UPDATE cash_events
SET instrument_id = (
    SELECT keep_id FROM duplicate_stock_instrument_map
    WHERE old_id = cash_events.instrument_id
)
WHERE instrument_id IN (SELECT old_id FROM duplicate_stock_instrument_map);

INSERT OR IGNORE INTO prices(instrument_id, date, close, currency, fetched_at)
SELECT map.keep_id, prices.date, prices.close, prices.currency, prices.fetched_at
FROM prices
JOIN duplicate_stock_instrument_map map ON map.old_id = prices.instrument_id;
DELETE FROM prices
WHERE instrument_id IN (SELECT old_id FROM duplicate_stock_instrument_map);

INSERT OR IGNORE INTO fund_data(
    instrument_id, asset_classes, sector_weightings, top_holdings,
    equity_metrics, fetched_at
)
SELECT map.keep_id, fund_data.asset_classes, fund_data.sector_weightings,
       fund_data.top_holdings, fund_data.equity_metrics, fund_data.fetched_at
FROM fund_data
JOIN duplicate_stock_instrument_map map ON map.old_id = fund_data.instrument_id;
DELETE FROM fund_data
WHERE instrument_id IN (SELECT old_id FROM duplicate_stock_instrument_map);

INSERT OR IGNORE INTO instrument_country_weights(instrument_id, country, weight_pct)
SELECT map.keep_id, weights.country, weights.weight_pct
FROM instrument_country_weights weights
JOIN duplicate_stock_instrument_map map ON map.old_id = weights.instrument_id;
DELETE FROM instrument_country_weights
WHERE instrument_id IN (SELECT old_id FROM duplicate_stock_instrument_map);

DELETE FROM instruments
WHERE id IN (SELECT old_id FROM duplicate_stock_instrument_map);

DROP TABLE duplicate_stock_instrument_map;

CREATE UNIQUE INDEX uq_instruments_isin_trading_currency
    ON instruments(isin, trading_currency)
    WHERE isin IS NOT NULL AND trading_currency IS NOT NULL;

CREATE UNIQUE INDEX uq_stock_instruments_isin
    ON instruments(isin)
    WHERE asset_type = 'stock' AND isin IS NOT NULL;

PRAGMA foreign_keys=ON;
