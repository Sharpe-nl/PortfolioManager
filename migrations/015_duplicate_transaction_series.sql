-- Remove transaction histories that were imported twice as a whole because a
-- newer broker CSV represented every raw row differently. Isolated identical
-- fills are deliberately left alone; only systematic series with at least two
-- dates and exactly two copies of every transaction are repaired.

CREATE TEMP TABLE duplicated_transaction_series AS
WITH semantic_groups AS (
    SELECT account_id, instrument_id, ts,
           CAST(quantity AS NUMERIC) AS stable_quantity,
           CAST(price AS NUMERIC) AS stable_price,
           local_currency,
           COALESCE(order_id, '') AS stable_order_id,
           COUNT(*) AS copies
    FROM transactions
    GROUP BY account_id, instrument_id, ts, stable_quantity, stable_price,
             local_currency, stable_order_id
), series AS (
    SELECT account_id, instrument_id,
           COUNT(*) AS transaction_count,
           COUNT(DISTINCT substr(ts, 1, 10)) AS transaction_dates,
           MIN(copies) AS minimum_copies,
           MAX(copies) AS maximum_copies
    FROM semantic_groups
    GROUP BY account_id, instrument_id
)
SELECT account_id, instrument_id
FROM series
WHERE transaction_count >= 2
  AND transaction_dates >= 2
  AND minimum_copies = 2
  AND maximum_copies = 2;

DELETE FROM transactions AS duplicate
WHERE EXISTS (
    SELECT 1
    FROM duplicated_transaction_series series
    WHERE series.account_id = duplicate.account_id
      AND series.instrument_id = duplicate.instrument_id
)
AND duplicate.id != (
    SELECT MIN(original.id)
    FROM transactions original
    WHERE original.account_id = duplicate.account_id
      AND original.instrument_id = duplicate.instrument_id
      AND original.ts = duplicate.ts
      AND CAST(original.quantity AS NUMERIC) = CAST(duplicate.quantity AS NUMERIC)
      AND CAST(original.price AS NUMERIC) = CAST(duplicate.price AS NUMERIC)
      AND original.local_currency = duplicate.local_currency
      AND COALESCE(original.order_id, '') = COALESCE(duplicate.order_id, '')
);

DROP TABLE duplicated_transaction_series;
