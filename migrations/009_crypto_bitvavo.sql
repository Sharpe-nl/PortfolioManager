CREATE TABLE IF NOT EXISTS crypto_assets (
    symbol TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    decimals INTEGER
);

CREATE TABLE IF NOT EXISTS crypto_balances (
    symbol TEXT PRIMARY KEY,
    available TEXT NOT NULL DEFAULT '0',
    in_order TEXT NOT NULL DEFAULT '0',
    staked TEXT NOT NULL DEFAULT '0',
    price_eur TEXT,
    value_eur TEXT NOT NULL DEFAULT '0',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS crypto_transactions (
    transaction_id TEXT PRIMARY KEY,
    executed_at TEXT NOT NULL,
    type TEXT NOT NULL,
    price_currency TEXT,
    price_amount TEXT,
    sent_currency TEXT,
    sent_amount TEXT,
    received_currency TEXT,
    received_amount TEXT,
    fees_currency TEXT,
    fees_amount TEXT,
    address TEXT
);

CREATE INDEX IF NOT EXISTS idx_crypto_transactions_executed
ON crypto_transactions(executed_at DESC);

CREATE TABLE IF NOT EXISTS crypto_prices (
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    close_eur TEXT NOT NULL,
    PRIMARY KEY(symbol, date)
);

CREATE TABLE IF NOT EXISTS crypto_portfolio_snapshots (
    captured_at TEXT PRIMARY KEY,
    total_eur TEXT NOT NULL,
    crypto_eur TEXT NOT NULL,
    cash_eur TEXT NOT NULL
);
