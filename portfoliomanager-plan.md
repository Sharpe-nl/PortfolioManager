# PortfolioManager — Implementation Plan

> **Instructions for the coding agent:** Build this project exactly as specified below. Work through the milestones in order. After each milestone, the app must be runnable and testable. Ask before deviating from the tech stack or data model. All code comments and UI text in **English**; the app must correctly parse **Dutch-language DeGiro CSV exports**.

---

## 1. Project Overview

PortfolioManager is a **self-hosted, single-user** web application for tracking personal investments across multiple accounts, inspired by portfoliodividendtracker.com. It runs in an **LXC container on a Proxmox NUC** (Debian 12, amd64) on the local network.

**Core capabilities:**
1. Import DeGiro CSV exports (regular account **and** DeGiro pension account) — transactions, dividends, cash movements.
2. Support additional manually-managed accounts (savings, other brokers) via manual entry or a generic CSV format.
3. A responsive dashboard (desktop + mobile) showing: total portfolio value, per-account breakdown, holdings, profit/loss, allocation by **sector**, **region**, and **asset type**.
4. **Dividend tracking and 12-month forward forecast.**
5. **Benchmark comparison** of portfolio performance vs. a chosen index fund (e.g. VWRL, S&P 500).

**Explicit non-goals (do NOT build):** multi-user support, live/automated broker API connections, trading/order execution, notifications, mobile apps (responsive web only), Docker (plain systemd deployment).

---

## 2. Tech Stack & Guiding Principles

**Primary principle: minimal, stable dependencies.** The owner does not want a project that breaks every month due to package churn. Prefer the Python standard library. Every third-party package must be justified.

**Allowed dependencies (pin exact versions in `requirements.txt`):**

| Package | Purpose | Justification |
|---|---|---|
| `fastapi` + `uvicorn` | Web framework + server | Small, stable API surface |
| `jinja2` | Server-side HTML templates | Stable for years |
| `python-multipart` | CSV file uploads in FastAPI | Required by FastAPI for form uploads |
| `yfinance` | Market prices, sector info, benchmark data, dividend calendar | The only realistic free data source; see §7 for isolation strategy |

**Explicitly NOT used:** React/Vue/npm build chain, ORM (use `sqlite3` from stdlib with raw SQL), pandas (use stdlib `csv`), any CSS framework requiring a build step.

**Frontend:** Server-rendered Jinja2 templates + a small amount of vanilla JavaScript. Charts via **Chart.js loaded from a local vendored copy** (download one pinned version into `static/vendor/chart.umd.js` — no CDN dependency, works offline on LAN). CSS: one hand-written `static/style.css`, mobile-first, CSS grid/flexbox. Optionally vendor **Pico.css** (classless, single file) as a base.

**Database:** SQLite, single file at `data/portfolio.db`. WAL mode. All money stored as **integer cents** or `TEXT` decimal handled with `decimal.Decimal` — never float for money.

**Python:** 3.14+. Type hints everywhere. `pytest` for tests (dev dependency only).

---

## 3. Architecture

```
portfoliomanager/
├── app/
│   ├── main.py            # FastAPI app, routes
│   ├── db.py              # sqlite3 connection, schema migrations (plain SQL files)
│   ├── models.py          # dataclasses for domain objects
│   ├── importers/
│   │   ├── degiro_transactions.py   # parses Transactions.csv
│   │   ├── degiro_account.py        # parses Account.csv (dividends, fees, cash)
│   │   └── generic.py               # generic CSV for other accounts
│   ├── services/
│   │   ├── portfolio.py   # holdings calculation, P/L, allocation
│   │   ├── dividends.py   # dividend history + forecast
│   │   ├── benchmark.py   # portfolio-vs-index comparison
│   │   └── prices.py      # price provider abstraction (see §7)
│   ├── templates/         # Jinja2
│   └── static/            # style.css, app.js, vendor/chart.umd.js
├── migrations/            # 001_init.sql, 002_...
├── data/                  # portfolio.db, price cache (gitignored)
├── tests/
│   ├── fixtures/          # sample DeGiro CSVs (anonymized)
│   └── test_*.py
├── deploy/
│   ├── portfoliomanager.service   # systemd unit
│   └── install.md
├── requirements.txt
└── README.md
```

The app is a single uvicorn process. No background workers: price refresh happens on-demand with caching (see §7), triggered by page load or a manual "refresh prices" button.

---

## 4. Data Model (SQLite)

```sql
-- accounts: DeGiro regular, DeGiro pension, savings, etc.
CREATE TABLE accounts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,                -- "DeGiro", "DeGiro Pensioen", "Savings ING"
    type TEXT NOT NULL,                -- 'broker' | 'pension' | 'savings' | 'other'
    currency TEXT NOT NULL DEFAULT 'EUR'
);

-- instruments: everything tradeable, identified primarily by ISIN
CREATE TABLE instruments (
    id INTEGER PRIMARY KEY,
    isin TEXT UNIQUE,
    name TEXT NOT NULL,
    symbol TEXT,                       -- yfinance ticker, may be NULL until mapped
    exchange TEXT,
    currency TEXT,
    asset_type TEXT,                   -- 'stock' | 'etf' | 'fund' | 'bond' | 'cash' | 'other'
    sector TEXT,                       -- manual override wins over provider data
    region TEXT
);

-- transactions: buys/sells from DeGiro Transactions.csv + manual entries
CREATE TABLE transactions (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    ts TEXT NOT NULL,                  -- ISO 8601
    quantity TEXT NOT NULL,            -- Decimal as text; negative = sell
    price TEXT NOT NULL,               -- per unit, local currency
    local_currency TEXT NOT NULL,
    fx_rate TEXT,                      -- local -> EUR
    value_eur TEXT NOT NULL,           -- total in EUR (negative = money out)
    fees_eur TEXT NOT NULL DEFAULT '0',
    order_id TEXT,                     -- DeGiro Order ID, used for dedup
    source TEXT NOT NULL,              -- 'degiro_csv' | 'manual'
    UNIQUE(account_id, order_id, ts, quantity, price)
);

-- cash_events: dividends, withholding tax, fees, deposits, interest
CREATE TABLE cash_events (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    instrument_id INTEGER REFERENCES instruments(id),   -- NULL for deposits/fees
    ts TEXT NOT NULL,
    type TEXT NOT NULL,               -- 'dividend' | 'dividend_tax' | 'fee' | 'deposit' | 'withdrawal' | 'interest' | 'other'
    amount_eur TEXT NOT NULL,
    description TEXT,
    dedup_hash TEXT UNIQUE            -- sha256 of raw CSV row, prevents double import
);

-- price cache
CREATE TABLE prices (
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    date TEXT NOT NULL,
    close TEXT NOT NULL,
    currency TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (instrument_id, date)
);

-- manual balance snapshots for non-broker accounts (savings etc.)
CREATE TABLE balance_snapshots (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    date TEXT NOT NULL,
    balance_eur TEXT NOT NULL,
    UNIQUE(account_id, date)
);

CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);  -- e.g. benchmark ticker
```

Holdings are **always derived** from transactions (sum of quantities per instrument per account) — never stored. Cost basis: average cost method.

---

## 5. DeGiro CSV Import

DeGiro provides two relevant exports (Dutch UI: *Overzichten → Transacties* and *Overzichten → Rekeningoverzicht*). Files are `utf-8` (sometimes with BOM), comma-separated, Dutch decimal format in some fields — parse defensively.

### 5.1 `Transactions.csv` (Transacties)
Typical Dutch header columns (order may vary; **map by header name, not index**):

```
Datum, Tijd, Product, ISIN, Beurs, Uitvoeringsplaats, Aantal, Koers, [ccy],
Lokale waarde, [ccy], Waarde, [ccy], Wisselkoers, Transactiekosten en/of, [ccy], Totaal, [ccy], Order ID
```

Notes:
- `Datum` format `dd-mm-yyyy`, `Tijd` `hh:mm`.
- Unnamed currency columns follow each amount column — handle headers that are empty strings.
- Negative `Aantal` = sell. `Waarde` is in EUR for EUR accounts.
- Dedup on `Order ID` + timestamp + quantity + price (some corporate actions have empty Order ID → fall back to full-row hash).
- Unknown ISINs create a new `instruments` row automatically.

### 5.2 `Account.csv` (Rekeningoverzicht)
Columns roughly:

```
Datum, Tijd, Valutadatum, Product, ISIN, Omschrijving, FX, Mutatie [ccy], [amount], Saldo [ccy], [amount], Order Id
```

Classify rows by `Omschrijving` (description) keywords, case-insensitive:
- `"Dividend"` → `cash_events.type = 'dividend'`
- `"Dividendbelasting"` → `'dividend_tax'`
- `"storting"` / `"Deposit"` / `"iDEAL"` → `'deposit'`
- `"onttrekking"` / `"Withdrawal"` → `'withdrawal'`
- `"kosten"` / `"Aansluitingskosten"` / `"transactiekosten"` → `'fee'`
- `"rente"` / `"interest"` → `'interest'`
- everything else → `'other'` (imported but flagged for review on an "unclassified rows" page)

Skip rows that merely mirror transactions already imported from Transactions.csv (descriptions like `"Koop"`/`"Verkoop"` — these are the cash legs of trades; import them only as informational, not double-counted in P/L).

**Every row gets a `dedup_hash` so re-uploading the same or an overlapping export is always safe (idempotent import).** This is critical: the workflow is "export from DeGiro every few weeks and upload the whole file again."

### 5.3 Import UX
- Upload page with account selector (which account does this file belong to) + file type auto-detection based on headers.
- After parsing, show a **preview screen**: N new rows, M duplicates skipped, K unclassified — then a confirm button.
- Import errors must never crash: collect row-level errors, show them, import the rest.

### 5.4 Generic CSV / manual entry (other accounts)
- Simple documented format: `date,type,isin_or_name,quantity,price,amount_eur,description`.
- Manual forms for: single transaction, cash event, balance snapshot (for savings accounts you only track a balance for).

---

## 6. Portfolio Calculations (`services/portfolio.py`)

All computed in EUR with `decimal.Decimal`:

- **Holdings per account and combined:** quantity, average cost, cost basis, current value (latest price × qty), unrealized P/L (€ and %), weight in portfolio.
- **Realized P/L** per instrument (average cost method).
- **Total return** including dividends (net of withholding tax) and fees.
- **Allocation views:** by sector, by region, by asset type, by account, by currency. Instruments without sector/region show as "Unclassified" — clicking through leads to an edit form (manual classification is stored on the `instruments` row and always wins over provider data).
- **Portfolio value over time:** daily series built from transaction history + cached historical prices; for savings accounts, interpolate between balance snapshots. Used for the main chart and benchmark comparison.

---

## 7. Price & Metadata Provider (`services/prices.py`)

`yfinance` is the one fragile dependency. Isolate it:

- Define a `PriceProvider` protocol with methods: `get_quote(ticker)`, `get_history(ticker, start, end)`, `get_info(ticker)` (sector, region, asset type), `get_dividends(ticker)`.
- One implementation: `YFinanceProvider`. All calls wrapped in try/except; on failure, **serve stale cached data and show a "prices as of <date>" badge** — the app must remain fully usable when yfinance is broken or offline.
- Cache aggressively in the `prices` table: quotes max once per hour, history/info max once per day. Never call yfinance during page render if cache is fresh.
- **ISIN → ticker mapping:** yfinance needs tickers, DeGiro gives ISINs. Attempt automatic resolution (yfinance supports ISIN lookup for many instruments); when it fails, the instrument appears on a "needs mapping" page where the owner enters the ticker manually (e.g. `VWRL.AS`). Store on `instruments.symbol`.
- Manual price entry fallback: for unmappable instruments (e.g. DeGiro pension funds, which often have no public ticker), allow entering a price manually; it's stored in `prices` like any other.

---

## 8. Dividend Tracking & Forecast (`services/dividends.py`)

- **History:** from imported `cash_events` (type `dividend`, minus `dividend_tax`). Views: per month (bar chart, last 24 months), per year, per instrument, trailing-12-month total, YoY growth.
- **Forecast (next 12 months):** for each holding, estimate forward dividend using, in order of preference: (1) provider dividend data (per-share dividend history from yfinance → project the same schedule forward), (2) trailing 12-month actual received dividends for that holding scaled by current quantity, (3) manual per-instrument annual dividend override field. Show forecast as a monthly bar chart with an "estimated" visual style, plus projected annual income and portfolio yield-on-cost.
- Clearly label all forecasts as estimates.

---

## 9. Benchmark Comparison (`services/benchmark.py`)

- Setting: benchmark ticker, default `VWRL.AS`; presets for `^GSPC` (S&P 500) and `IWDA.AS`.
- Method: **"what if the same cash flows had bought the benchmark"** — replay every deposit/withdrawal (or alternatively every buy/sell cash flow; implement the deposit-based variant) as hypothetical benchmark purchases at that day's benchmark close. Produces a fair time-weighted comparison for a portfolio with ongoing contributions.
- Output: line chart of actual portfolio value vs. hypothetical benchmark value over time, plus summary stats (total return %, XIRR of both). Implement XIRR with a simple stdlib Newton–Raphson — no scipy.

---

## 10. UI / Pages

Server-rendered, mobile-first responsive. Bottom tab bar on mobile, sidebar on desktop.

1. **Dashboard** (`/`): total value (all accounts), today/total P/L, value-over-time chart with range selector (1M/YTD/1Y/All), allocation donuts (sector / region / asset type — tabbed on mobile), top holdings, dividends received this month, next expected dividends.
2. **Holdings** (`/holdings`): sortable table (mobile: card list) — name, account, qty, avg cost, price, value, P/L €/%, weight. Filter by account. Row click → instrument detail.
3. **Instrument detail** (`/instrument/{id}`): position summary, transaction history, dividend history, edit form (ticker mapping, sector/region/asset type overrides, manual dividend override).
4. **Dividends** (`/dividends`): history charts + 12-month forecast + per-instrument table.
5. **Benchmark** (`/benchmark`): comparison chart + stats + benchmark selector.
6. **Accounts** (`/accounts`): list, add/edit accounts, per-account value & snapshots.
7. **Import** (`/import`): upload + preview + confirm; import history log; "needs mapping" and "unclassified rows" sections.
8. **Settings** (`/settings`): benchmark default, manual price entry, database backup download button (streams the SQLite file).

Design: clean, data-dense but calm; dark-mode friendly via `prefers-color-scheme`. Green/red only for P/L values. All numbers formatted with Dutch locale conventions (€ 1.234,56) via a Jinja2 filter — no locale packages, hand-write the formatter.

**Security:** LAN-only app, but add a single shared-password login (session cookie, password hash in `settings`, stdlib `hashlib.scrypt`). No user management.

---

## 11. Deployment (LXC on Proxmox)

Provide `deploy/install.md` with copy-paste commands:

1. Debian 12 LXC (1 vCPU, 512 MB–1 GB RAM, 4 GB disk is plenty).
2. `apt install python3.14 python3.14-venv git`
3. Clone repo to `/opt/portfoliomanager`, create venv, `pip install -r requirements.txt`.
4. systemd unit (`deploy/portfoliomanager.service`): runs `uvicorn app.main:app --host 0.0.0.0 --port 8000` as a dedicated non-root user, `Restart=always`, `WorkingDirectory=/opt/portfoliomanager`.
5. Backup: nightly cron copying `data/portfolio.db` (use `sqlite3 .backup`) to a dated file, keep 30; document how to point this at a Proxmox-backed mount.
6. Update procedure: `git pull && pip install -r requirements.txt && systemctl restart portfoliomanager`.

No reverse proxy required (LAN), but document optional Caddy/nginx + HTTPS in one short paragraph.

---

## 12. Milestones (implement in this order)

**M1 — Skeleton & DB:** project layout, FastAPI app, SQLite schema + migration runner, base template with nav, settings page, password login. *Done when: app runs, login works, empty dashboard renders.*

**M2 — DeGiro import:** both CSV parsers with header-based mapping, dedup, preview/confirm flow, account management, generic CSV + manual entry. Include anonymized fixture CSVs and thorough parser unit tests (dedup, re-import idempotency, malformed rows, BOM, empty headers, negative quantities). *Done when: uploading real exports twice yields zero duplicates.*

**M3 — Portfolio core:** holdings, cost basis, realized/unrealized P/L, holdings page, instrument detail, allocation calculations with manual classification, dashboard v1 (no live prices yet — last transaction price as placeholder).

**M4 — Prices:** `PriceProvider` + yfinance implementation, caching, ISIN→ticker mapping flow, manual prices, stale-data badge, value-over-time series, dashboard charts (Chart.js vendored).

**M5 — Dividends:** history views + forecast engine + dividends page.

**M6 — Benchmark:** cash-flow replay engine, XIRR, benchmark page.

**M7 — Polish & deploy:** mobile refinements, dark mode, error pages, backup button, `deploy/` files, README with screenshots of the import workflow, final test pass.

---

## 13. Testing & Quality Bar

- `pytest` unit tests for: both CSV parsers (highest priority — fixtures for edge cases), cost-basis math, dividend forecast, XIRR, dedup logic. Money math tests must assert exact `Decimal` values.
- No network calls in tests: fake `PriceProvider` implementation.
- Target: parsers and calculation services ≥ 90% coverage; routes smoke-tested.
- `ruff` for linting (dev-only dependency).

## 14. Open Questions for the Owner (ask before M2 if unclear)

1. DeGiro pension exports may differ slightly from the regular account exports — request one real (anonymized) sample of each before finalizing the parsers.
2. Confirm whether non-EUR positions exist (affects FX handling priority).
