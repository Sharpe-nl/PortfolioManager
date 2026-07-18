-- Savings accounts: dashboard visibility, rate history and manual interest corrections.
ALTER TABLE accounts ADD COLUMN include_in_dashboard INTEGER NOT NULL DEFAULT 1;

CREATE TABLE IF NOT EXISTS savings_interest_rates (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    annual_rate TEXT NOT NULL,
    payout_frequency TEXT NOT NULL CHECK(payout_frequency IN ('weekly','monthly','yearly')),
    starts_on TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(account_id, starts_on)
);

CREATE TABLE IF NOT EXISTS savings_interest_adjustments (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    amount_eur TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_savings_rates_account_date
    ON savings_interest_rates(account_id, starts_on);
CREATE INDEX IF NOT EXISTS idx_savings_adjustments_account_date
    ON savings_interest_adjustments(account_id, date);
