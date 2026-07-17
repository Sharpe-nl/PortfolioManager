-- Migration 005: ETF/fund composition data (top holdings, sector
-- weightings, asset-class split, equity metrics) from yfinance's
-- Ticker.funds_data API. Stored as JSON blobs — this is cached, periodically
-- refreshed provider data (like prices), not something the app computes, so
-- normalizing it into several tables would add no value.

CREATE TABLE IF NOT EXISTS fund_data (
    instrument_id      INTEGER PRIMARY KEY REFERENCES instruments(id),
    asset_classes      TEXT,    -- JSON: {"stockPosition": 0.98, "cashPosition": 0.02, ...}
    sector_weightings  TEXT,    -- JSON: {"technology": 0.25, "financial_services": 0.15, ...}
    top_holdings       TEXT,    -- JSON: [{"symbol": "AAPL", "name": "Apple Inc", "percent": 0.05}, ...]
    equity_metrics     TEXT,    -- JSON: {"price_earnings": 18.2, "price_book": 2.1, ...}
    fetched_at         TEXT NOT NULL
);
