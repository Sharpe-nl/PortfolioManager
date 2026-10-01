-- Keep the interest accrual period separate from the date on which it is paid.
ALTER TABLE savings_interest_rates ADD COLUMN payout_on TEXT;
