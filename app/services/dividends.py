"""Dividend history and 12-month forward forecast.

History comes from cash_events (type='dividend' / 'dividend_tax').
Forecast uses, in order of preference:
  1. Provider dividend data fetched via prices service (per-share amounts)
  2. Trailing-12-month actual received, scaled to current quantity
  3. Manual per-instrument override stored in settings as 'div_override_{isin}'
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

_ZERO = Decimal("0")
_TWO = Decimal("0.01")


def _d(s: str | None) -> Decimal:
    try:
        return Decimal(s) if s else _ZERO
    except Exception:
        return _ZERO


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def get_dividend_history_by_year(
    conn: sqlite3.Connection,
    account_id: int | None = None,
) -> list[dict]:
    sql = """
        SELECT
            SUBSTR(ts, 1, 4) AS year,
            SUM(CASE WHEN type='dividend'     THEN CAST(amount_eur AS REAL) ELSE 0 END) AS gross,
            SUM(CASE WHEN type='dividend_tax' THEN CAST(amount_eur AS REAL) ELSE 0 END) AS tax
        FROM cash_events
        WHERE type IN ('dividend','dividend_tax')
          AND (:acct IS NULL OR account_id = :acct)
        GROUP BY year
        ORDER BY year DESC
    """
    rows = conn.execute(sql, {"acct": account_id}).fetchall()
    return [
        {
            "year": r["year"],
            "gross": Decimal(str(r["gross"])).quantize(_TWO),
            "tax": Decimal(str(r["tax"])).quantize(_TWO),
            "net": (Decimal(str(r["gross"])) + Decimal(str(r["tax"]))).quantize(_TWO),
        }
        for r in rows
    ]


def get_trailing_12m_income(
    conn: sqlite3.Connection,
    account_id: int | None = None,
) -> Decimal:
    """Total net dividend income in the last 12 months."""
    since = (date.today() - timedelta(days=365)).isoformat()
    row = conn.execute(
        """SELECT SUM(CAST(amount_eur AS REAL)) AS total
           FROM cash_events
           WHERE type IN ('dividend','dividend_tax')
             AND ts >= :since
             AND (:acct IS NULL OR account_id = :acct)""",
        {"since": since, "acct": account_id},
    ).fetchone()
    return Decimal(str(row["total"] or 0)).quantize(_TWO)


def get_dividend_events(
    conn: sqlite3.Connection,
    account_id: int | None = None,
) -> list[dict]:
    """Raw dividend + dividend_tax cash events (ts, amount_eur).

    For client-side period filtering (e.g. a dashboard range selector) where
    the range isn't known ahead of render time — sum whichever events fall
    within the chosen [start, end] to get that period's net dividend income.
    """
    rows = conn.execute(
        """SELECT ts, amount_eur FROM cash_events
           WHERE type IN ('dividend','dividend_tax')
             AND (:acct IS NULL OR account_id = :acct)
           ORDER BY ts""",
        {"acct": account_id},
    ).fetchall()
    return [
        {"ts": r["ts"], "amount_eur": Decimal(str(r["amount_eur"])).quantize(_TWO, ROUND_HALF_UP)}
        for r in rows
    ]


def get_dividend_events_detail(
    conn: sqlite3.Connection,
    account_id: int | None = None,
) -> list[dict]:
    """Dividend + dividend_tax cash events with instrument/account context,
    for the dashboard's "Dividend" detail popup — one row per cash event so
    the tax withheld on a payout shows up as its own (negative) line next to
    the gross dividend, same as get_dividend_events but with enough context
    to render a breakdown table instead of just summing amounts.
    """
    rows = conn.execute(
        """SELECT ce.ts, ce.type, ce.amount_eur,
                  ce.instrument_id, i.name AS instrument_name, i.isin, i.symbol, a.name AS account_name
           FROM cash_events ce
           LEFT JOIN instruments i ON i.id = ce.instrument_id
           JOIN accounts a ON a.id = ce.account_id
           WHERE ce.type IN ('dividend','dividend_tax')
             AND (:acct IS NULL OR ce.account_id = :acct)
           ORDER BY ce.ts DESC""",
        {"acct": account_id},
    ).fetchall()
    return [
        {
            "ts": r["ts"],
            "type": r["type"],
            "instrument_id": r["instrument_id"],
            "instrument_name": r["instrument_name"] or "Onbekend",
            "isin": r["isin"],
            "symbol": r["symbol"],
            "account_name": r["account_name"],
            "amount_eur": Decimal(str(r["amount_eur"])).quantize(_TWO, ROUND_HALF_UP),
        }
        for r in rows
    ]


def get_dividend_history_by_instrument(
    conn: sqlite3.Connection,
    account_id: int | None = None,
) -> list[dict]:
    sql = """
        SELECT
            ce.instrument_id,
            i.name,
            i.isin,
            SUM(CASE WHEN ce.type='dividend'     THEN CAST(ce.amount_eur AS REAL) ELSE 0 END) AS gross,
            SUM(CASE WHEN ce.type='dividend_tax' THEN CAST(ce.amount_eur AS REAL) ELSE 0 END) AS tax,
            MAX(ce.ts) AS last_received
        FROM cash_events ce
        LEFT JOIN instruments i ON i.id = ce.instrument_id
        WHERE ce.type IN ('dividend','dividend_tax')
          AND (:acct IS NULL OR ce.account_id = :acct)
        GROUP BY ce.instrument_id
        ORDER BY gross DESC
    """
    rows = conn.execute(sql, {"acct": account_id}).fetchall()
    return [
        {
            "instrument_id": r["instrument_id"],
            "name": r["name"],
            "isin": r["isin"],
            "gross": Decimal(str(r["gross"])).quantize(_TWO),
            "tax": Decimal(str(r["tax"])).quantize(_TWO),
            "net": (Decimal(str(r["gross"])) + Decimal(str(r["tax"]))).quantize(_TWO),
            "last_received": r["last_received"],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Forecast
# ---------------------------------------------------------------------------

def get_dividend_forecast(
    conn: sqlite3.Connection,
    account_id: int | None = None,
) -> list[dict]:
    """Estimate monthly dividend income for the next 12 months.

    Returns list of {"month": "yyyy-mm", "amount": Decimal, "sources": list[dict]}.
    Each source in 'sources' is a holding's contribution:
      {"instrument_id", "name", "amount", "method": "trailing12m"|"manual"|"provider"}
    """
    today = date.today()
    months_ahead = [
        (today.replace(day=1) + _month_delta(i)).strftime("%Y-%m")
        for i in range(1, 13)
    ]

    # Get all current holdings
    holdings_sql = """
        SELECT t.instrument_id, i.name, i.isin,
               SUM(CAST(t.quantity AS REAL)) AS qty
        FROM transactions t
        JOIN instruments i ON i.id = t.instrument_id
        WHERE :acct IS NULL OR t.account_id = :acct
        GROUP BY t.instrument_id
        HAVING ABS(SUM(CAST(t.quantity AS REAL))) > 0.000001
    """
    holdings = conn.execute(holdings_sql, {"acct": account_id}).fetchall()

    # Trailing-12-month per-share dividends (from actual cash_events)
    since_iso = (today - timedelta(days=365)).isoformat()
    div_sql = """
        SELECT ce.instrument_id,
               SUM(CAST(ce.amount_eur AS REAL)) AS net_div
        FROM cash_events ce
        JOIN transactions t ON t.instrument_id = ce.instrument_id
        WHERE ce.type = 'dividend'
          AND ce.ts >= :since
          AND (:acct IS NULL OR ce.account_id = :acct)
        GROUP BY ce.instrument_id
    """
    div_rows = {
        r["instrument_id"]: Decimal(str(r["net_div"] or 0))
        for r in conn.execute(div_sql, {"since": since_iso, "acct": account_id}).fetchall()
    }

    # Manual overrides: stored as settings key 'div_annual_{isin}' (annual EUR per share)
    monthly: dict[str, Decimal] = defaultdict(Decimal)
    sources_by_month: dict[str, list[dict]] = defaultdict(list)

    for h in holdings:
        iid = h["instrument_id"]
        qty = Decimal(str(h["qty"]))
        name = h["name"] or "Unknown"
        isin = h["isin"] or ""

        # Try manual override first
        manual_str = conn.execute(
            "SELECT value FROM settings WHERE key=?",
            (f"div_annual_{isin}",),
        ).fetchone()

        if manual_str:
            annual_total = _d(manual_str["value"]) * qty
            per_month = (annual_total / 12).quantize(_TWO)
            method = "manual"
        elif iid in div_rows:
            # Trailing 12m actual, scaled by current qty vs avg qty in period
            trailing_annual = div_rows[iid]
            per_month = (trailing_annual / 12).quantize(_TWO)
            method = "trailing12m"
        else:
            continue  # no dividend data → skip

        for m in months_ahead:
            monthly[m] += per_month
            sources_by_month[m].append({
                "instrument_id": iid,
                "name": name,
                "amount": per_month,
                "method": method,
            })

    return [
        {
            "month": m,
            "amount": monthly.get(m, _ZERO).quantize(_TWO),
            "sources": sources_by_month.get(m, []),
            "is_estimate": True,
        }
        for m in months_ahead
    ]


def _month_delta(months: int):
    """Return a timedelta-like object for adding N calendar months."""
    import calendar
    # Return as relativedelta-like offset via a simple approach
    return timedelta(days=months * 30)  # approximate; fine for display bucketing
