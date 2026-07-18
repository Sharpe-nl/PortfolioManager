-- A savings rate can end and can have bonus tiers, for example 1.5% up to
-- €19,000 and 3% for the part above that amount.
ALTER TABLE savings_interest_rates ADD COLUMN ends_on TEXT;

CREATE TABLE IF NOT EXISTS savings_interest_rate_tiers (
    id INTEGER PRIMARY KEY,
    rate_id INTEGER NOT NULL REFERENCES savings_interest_rates(id) ON DELETE CASCADE,
    min_balance_eur TEXT NOT NULL,
    annual_rate TEXT NOT NULL,
    UNIQUE(rate_id, min_balance_eur)
);

CREATE INDEX IF NOT EXISTS idx_savings_rate_tiers_rate
    ON savings_interest_rate_tiers(rate_id, min_balance_eur);
