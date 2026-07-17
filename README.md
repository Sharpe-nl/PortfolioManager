# PortfolioManager

Self-hosted investment portfolio tracker for personal use.
Runs as a single Python process on a Debian 12 LXC (Proxmox).

## Features

- Import DeGiro Transactions.csv and Account.csv (Dutch format, idempotent re-import)
- Manual accounts (savings, other brokers) via generic CSV or manual entry
- Dashboard: total value, P/L, portfolio value chart, allocation by sector/region/type
- Holdings table with average cost and unrealized P/L
- Dividend history (24 months) + 12-month forward forecast
- Benchmark comparison (VWRL, IWDA, S&P 500) with XIRR
- Live prices via yfinance with local SQLite cache (works offline when stale)
- YubiKey / FIDO2 authentication (WebAuthn)
- Database backup download from the UI
- Mobile-first responsive UI (Pico.css + Chart.js, no build step)

## Quick start (development)

```bash
# 1 — Clone and create a virtual environment
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2 — Download vendor assets (Chart.js, Pico.css)
python scripts/download_vendors.py

# 3 — Run (HTTP mode for localhost dev — WebAuthn works on localhost over HTTP)
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 \
    --no-use-colors 2>&1
```

> **Note:** The session middleware is configured with `https_only=True` for
> production.  For local development, edit `app/main.py` and set
> `https_only=False` temporarily, or use `127.0.0.1` (WebAuthn allows HTTP
> on localhost).

Then open `http://127.0.0.1:8000` in your browser.  On the first visit you
will be prompted to register your YubiKey (or any FIDO2 authenticator).

## Production deployment

See [deploy/install.md](deploy/install.md) for full step-by-step instructions.

## Running tests

```bash
pytest tests/ -v
```

## Project structure

```
app/
├── main.py            FastAPI app, middleware, startup
├── db.py              SQLite connection, migration runner, settings helpers
├── models.py          Domain dataclasses
├── auth.py            WebAuthn/FIDO2 helpers
├── helpers.py         Jinja2 template engine, auth dependency, filters
├── routers/           Route handlers (one file per feature area)
├── importers/         CSV parsers (DeGiro transactions, account, generic)
├── services/          Business logic (portfolio, prices, dividends, benchmark)
├── templates/         Jinja2 HTML templates
└── static/            CSS, JS, vendor assets

migrations/            SQL schema migrations (run automatically on startup)
tests/                 pytest tests with fixture CSVs
deploy/                systemd unit + install guide
scripts/               download_vendors.py
data/                  portfolio.db, TLS certs (gitignored)
```

## DeGiro CSV format notes

**Transactions.csv** — amount columns come before their currency column.
Example: `Koers` = price value, next unnamed column = price currency.

**Account.csv** — the `Mutatie` column contains the **currency code**,
and the next unnamed column contains the **amount**.  This is the opposite
of transactions.csv — the parser handles both correctly.

Uploading the same or overlapping exports multiple times is always safe:
every row carries a `dedup_hash` (SHA-256 of the raw CSV row) so duplicates
are detected and silently skipped.

## Tech stack

| Layer       | Library                     |
|-------------|------------------------------|
| Web         | FastAPI + uvicorn            |
| Templates   | Jinja2 (server-rendered)     |
| CSS         | Pico.css (vendored) + custom |
| Charts      | Chart.js (vendored)          |
| Database    | SQLite 3, WAL mode, raw SQL  |
| Prices      | yfinance (isolated behind protocol) |
| Auth        | WebAuthn via py_webauthn     |
| Money       | `decimal.Decimal` everywhere, stored as TEXT |

## License

Personal use only.
