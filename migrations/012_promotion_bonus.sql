-- A DEGIRO "Verrekening Promotie" is a credited bonus, not an unprocessed
-- cash event. Reclassify existing imports so it no longer appears in the
-- review queue and receives the same treatment as newly imported rows.
UPDATE cash_events
SET type = 'bonus'
WHERE type = 'other'
  AND lower(description) LIKE '%verrekening promotie%';
