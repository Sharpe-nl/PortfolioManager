-- Migration 014 merged duplicate stock instruments but preserved both linked
-- transaction sets. Migration 015 only repaired instruments for which every
-- transaction was duplicated, so one correct singleton could leave the exact
-- double rows in place. Repair those duplicated economic transactions when
-- the pattern occurs on at least two distinct dates. The comparison uses the
-- fields shown in transaction history; internal import metadata is irrelevant.

CREATE TEMP TABLE transaction_rows_to_remove AS
WITH ranked AS (
    SELECT id,
           account_id,
           instrument_id,
           ts,
           ROW_NUMBER() OVER (
               PARTITION BY account_id, instrument_id, ts,
                            CAST(quantity AS NUMERIC),
                            CAST(price AS NUMERIC),
                            local_currency,
                            CAST(value_eur AS NUMERIC),
                            CAST(fees_eur AS NUMERIC)
               ORDER BY id
           ) AS occurrence,
           COUNT(*) OVER (
               PARTITION BY account_id, instrument_id, ts,
                            CAST(quantity AS NUMERIC),
                            CAST(price AS NUMERIC),
                            local_currency,
                            CAST(value_eur AS NUMERIC),
                            CAST(fees_eur AS NUMERIC)
           ) AS copies
    FROM transactions
), duplicated_series AS (
    SELECT account_id, instrument_id
    FROM ranked
    WHERE copies = 2
    GROUP BY account_id, instrument_id
    HAVING COUNT(DISTINCT substr(ts, 1, 10)) >= 2
)
SELECT ranked.id
FROM ranked
JOIN duplicated_series
  ON duplicated_series.account_id = ranked.account_id
 AND duplicated_series.instrument_id = ranked.instrument_id
WHERE ranked.copies = 2
  AND ranked.occurrence = 2;

DELETE FROM transactions
WHERE id IN (SELECT id FROM transaction_rows_to_remove);

DROP TABLE transaction_rows_to_remove;
