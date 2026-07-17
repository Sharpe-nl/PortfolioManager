"""Price provider abstraction.

All yfinance calls are isolated here.  The rest of the app only calls
functions in this module — it never imports yfinance directly.

Caching rules (enforced here, not by callers):
  • Quotes:  at most once per hour
  • History / info:  at most once per day

If yfinance fails, stale cached data is served.  The caller receives a
``stale`` flag in the return dict so the UI can display a "prices as of
<date>" badge.
"""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional, Protocol


# ---------------------------------------------------------------------------
# Protocol (for future alternative implementations / testing)
# ---------------------------------------------------------------------------

class PriceProvider(Protocol):
    def get_quote(self, ticker: str) -> Optional[dict]: ...
    def get_history(self, ticker: str, start: str, end: str) -> list[dict]: ...
    def get_info(self, ticker: str) -> Optional[dict]: ...
    def get_dividends(self, ticker: str) -> list[dict]: ...
    def get_fund_data(self, ticker: str) -> Optional[dict]: ...


# ---------------------------------------------------------------------------
# yfinance implementation
# ---------------------------------------------------------------------------
# curl_cffi is auto-detected by yfinance when installed — do NOT create or pass
# a curl_cffi session manually to yf.Ticker/yf.download; that triggers a known
# "'str' object has no attribute 'name'" bug inside yfinance's internals.
# Just install curl_cffi (requirements.txt) and yfinance uses it automatically.


class YFinanceProvider:
    def get_quote(self, ticker: str) -> Optional[dict]:
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            fi = t.fast_info
            return {
                "price": float(fi.last_price) if fi.last_price else None,
                "currency": fi.currency or "USD",
            }
        except Exception:
            return None

    def get_history(self, ticker: str, start: str, end: str) -> list[dict]:
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            df = t.history(start=start, end=end, auto_adjust=True)
            if df is None or df.empty:
                return []
            currency = getattr(t.fast_info, "currency", None) or "USD"
            return [
                {"date": str(idx.date()), "close": float(row["Close"]), "currency": currency}
                for idx, row in df.iterrows()
            ]
        except Exception:
            return []

    def get_recent(self, ticker: str, period: str = "5d") -> list[dict]:
        """Fetch recent closes using a period string (e.g. '5d', '1mo', '1y').

        curl_cffi is auto-detected by yfinance when installed — do NOT pass a
        session manually; that triggers a known 'str has no attribute name' bug.
        Returns rows sorted oldest→newest.
        """
        import sys
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            df = t.history(period=period, auto_adjust=True)
            if df is None or df.empty:
                print(f"[price-refresh]   {ticker}: empty dataframe for period={period}", file=sys.stderr, flush=True)
                return []
            currency = getattr(t.fast_info, "currency", None) or "EUR"
            return [
                {"date": str(idx.date()), "close": float(row["Close"]), "currency": currency}
                for idx, row in df.iterrows()
            ]
        except Exception as exc:
            print(f"[price-refresh]   {ticker}: exception: {exc}", file=sys.stderr, flush=True)
            return []

    def get_info(self, ticker: str) -> Optional[dict]:
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            info = t.info or {}
            return {
                "sector": info.get("sector"),
                # ETFs/funds hold many sectors, so yfinance reports no
                # "sector" for them — but does report a Morningstar-style
                # "category" (e.g. "World Large-Cap Blend Equity"), which is
                # a much more useful sector-chart label than "Unclassified".
                "category": info.get("category"),
                "industry": info.get("industry"),
                "country": info.get("country"),
                "asset_type": _infer_asset_type(info),
                "currency": info.get("currency"),
                "exchange": info.get("exchange"),
            }
        except Exception:
            return None

    def get_dividends(self, ticker: str) -> list[dict]:
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            divs = t.dividends
            if divs is None or divs.empty:
                return []
            return [
                {"date": str(d.date()), "amount": float(v)}
                for d, v in divs.items()
            ]
        except Exception:
            return []

    def get_fund_data(self, ticker: str) -> Optional[dict]:
        """ETF/fund composition: asset classes, sector weightings, top
        holdings, equity metrics. Returns None for tickers with no fund data
        (e.g. individual stocks) or on error — never raises.
        """
        try:
            import yfinance as yf
            fd = yf.Ticker(ticker).funds_data
            if fd is None:
                return None

            asset_classes = {k: _safe_float(v) for k, v in (fd.asset_classes or {}).items()}
            asset_classes = {k: v for k, v in asset_classes.items() if v is not None}

            sector_weightings = {k: _safe_float(v) for k, v in (fd.sector_weightings or {}).items()}
            sector_weightings = {k: v for k, v in sector_weightings.items() if v is not None}

            top_holdings = []
            df = fd.top_holdings
            if df is not None and not df.empty:
                for symbol, row in df.iterrows():
                    top_holdings.append({
                        "symbol": symbol,
                        "name": row.get("Name"),
                        "percent": _safe_float(row.get("Holding Percent")),
                    })

            equity_metrics = {}
            eq_df = fd.equity_holdings
            if eq_df is not None and not eq_df.empty and ticker in eq_df.columns:
                for metric_name, value in eq_df[ticker].items():
                    v = _safe_float(value)
                    if v is not None:
                        equity_metrics[metric_name] = v

            if not (asset_classes or sector_weightings or top_holdings or equity_metrics):
                return None  # not a fund, or Yahoo has nothing for it

            return {
                "asset_classes": asset_classes,
                "sector_weightings": sector_weightings,
                "top_holdings": top_holdings,
                "equity_metrics": equity_metrics,
            }
        except Exception:
            return None


_default_provider = YFinanceProvider()


def _infer_asset_type(info: dict) -> str:
    quote_type = (info.get("quoteType") or "").lower()
    mapping = {"etf": "etf", "mutualfund": "fund", "bond": "bond", "equity": "stock"}
    return mapping.get(quote_type, "other")


def _safe_float(value) -> Optional[float]:
    """Coerce a provider value (possibly pandas NA/NaN/None/non-numeric) to a
    finite float, or None. Never lets a NaN slip into stored JSON — learned
    the hard way earlier with NaN prices poisoning downstream Decimal math.
    """
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

_QUOTE_TTL_HOURS = 1
_HISTORY_TTL_HOURS = 24


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_cached_price(
    conn: sqlite3.Connection,
    instrument_id: int,
    for_date: str | None = None,
) -> Optional[dict]:
    """Return the most recent cached price for an instrument.

    If for_date is given, return the price for that exact date (or None).
    If for_date is None, return the latest available cached price.
    """
    if for_date:
        row = conn.execute(
            "SELECT close, currency, date, fetched_at FROM prices "
            "WHERE instrument_id=? AND date=?",
            (instrument_id, for_date),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT close, currency, date, fetched_at FROM prices "
            "WHERE instrument_id=? ORDER BY date DESC LIMIT 1",
            (instrument_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "close": Decimal(row["close"]),
        "currency": row["currency"],
        "date": row["date"],
        "fetched_at": row["fetched_at"],
        "stale": False,
    }


def _is_quote_stale(fetched_at: str) -> bool:
    try:
        ts = datetime.fromisoformat(fetched_at)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts) > timedelta(hours=_QUOTE_TTL_HOURS)
    except Exception:
        return True


def _is_history_stale(fetched_at: str) -> bool:
    try:
        ts = datetime.fromisoformat(fetched_at)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts) > timedelta(hours=_HISTORY_TTL_HOURS)
    except Exception:
        return True


def _store_price(
    conn: sqlite3.Connection, instrument_id: int, date_str: str,
    close: float, currency: str,
) -> None:
    if not math.isfinite(close):
        # yfinance occasionally returns NaN closes (e.g. illiquid tickers,
        # bad ISIN→ticker mappings). Storing "NaN" as text poisons every
        # downstream Decimal calculation that reads this row back.
        return
    conn.execute(
        """INSERT INTO prices(instrument_id, date, close, currency, fetched_at)
           VALUES (?,?,?,?,?)
           ON CONFLICT(instrument_id, date) DO UPDATE
           SET close=excluded.close, currency=excluded.currency,
               fetched_at=excluded.fetched_at""",
        (instrument_id, date_str, str(Decimal(str(close))), currency, _now_utc()),
    )


# ---------------------------------------------------------------------------
# FX conversion: native price → EUR
# ---------------------------------------------------------------------------
# All prices are stored in EUR so that avg_cost (which comes from value_eur,
# already in EUR) and current_price are always in the same unit.
#
# EUR{CCY}=X gives "units of CCY per 1 EUR" (e.g. EURUSD=X = 1.08 means
# 1 EUR = 1.08 USD).  To convert native → EUR: price / divisor / rate.
# GBp (pence) uses divisor=100 because 100 pence = 1 GBP.

_EUR_RATE_TICKERS: dict[str, tuple[str, float]] = {
    # currency: (yfinance_fx_ticker,  native_units_per_base)
    "USD": ("EURUSD=X",  1.0),
    "GBP": ("EURGBP=X",  1.0),
    "GBp": ("EURGBP=X", 100.0),   # London Stock Exchange reports in pence
    "CHF": ("EURCHF=X",  1.0),
    "JPY": ("EURJPY=X",  1.0),
    "SEK": ("EURSEK=X",  1.0),
    "NOK": ("EURNOK=X",  1.0),
    "DKK": ("EURDKK=X",  1.0),
    "PLN": ("EURPLN=X",  1.0),
    "CZK": ("EURCZK=X",  1.0),
    "HKD": ("EURHKD=X",  1.0),
    "AUD": ("EURAUD=X",  1.0),
    "CAD": ("EURCAD=X",  1.0),
    "SGD": ("EURSGD=X",  1.0),
}

# Module-level cache: {normalised_currency: EUR_rate or None}
# Populated lazily; survives for the lifetime of the process (refreshed
# once per price-refresh run is fine for a personal portfolio tool).
_fx_rate_cache: dict[str, Optional[float]] = {}


def _fetch_eur_rate_from_yf(currency: str) -> Optional[float]:
    """Fetch the EUR/{currency} rate from yfinance.

    Returns R from EUR{CCY}=X so that:
        price_eur = (native_price / divisor) / R
    Returns None on any error.
    """
    entry = _EUR_RATE_TICKERS.get(currency)
    if not entry:
        return None
    fx_ticker, _divisor = entry
    try:
        import yfinance as yf
        import sys
        t = yf.Ticker(fx_ticker)
        df = t.history(period="5d", auto_adjust=False)
        if df is not None and not df.empty:
            rate = float(df["Close"].iloc[-1])
            print(f"[fx-rate] {fx_ticker} = {rate:.6f}  ({currency}→EUR)", file=sys.stderr, flush=True)
            return rate
    except Exception as exc:
        import sys
        print(f"[fx-rate] failed to fetch {fx_ticker}: {exc}", file=sys.stderr, flush=True)
    return None


def _to_eur(native_price: float, currency: str) -> float:
    """Convert a native price to EUR using the module-level FX cache.

    Fetches the FX rate from yfinance on first call per currency (then caches).
    Falls back to the native price unchanged if conversion is impossible
    (unknown currency or network error) — callers should log a warning.
    """
    if currency == "EUR":
        return native_price

    # Normalise GBp → GBP for cache lookup (same FX ticker, different divisor)
    cache_key = "GBP" if currency == "GBp" else currency

    if cache_key not in _fx_rate_cache:
        _fx_rate_cache[cache_key] = _fetch_eur_rate_from_yf(currency)

    rate = _fx_rate_cache.get(cache_key)
    if not rate:
        return native_price  # fallback: return unconverted (logged by caller)

    entry = _EUR_RATE_TICKERS.get(currency)
    divisor = entry[1] if entry else 1.0
    return (native_price / divisor) / rate


def to_eur_live(amount: Decimal, currency: str) -> Optional[Decimal]:
    """Convert `amount` in `currency` to EUR using today's FX rate.

    Unlike `_to_eur`, returns None (rather than silently falling back to the
    unconverted amount) when no live rate is available, so callers can
    explicitly fall back to a different estimate (e.g. a historical rate)
    instead of unknowingly treating foreign currency as EUR 1:1.
    """
    if currency == "EUR":
        return amount
    cache_key = "GBP" if currency == "GBp" else currency
    if cache_key not in _fx_rate_cache:
        _fx_rate_cache[cache_key] = _fetch_eur_rate_from_yf(currency)
    rate = _fx_rate_cache.get(cache_key)
    if not rate:
        return None
    entry = _EUR_RATE_TICKERS.get(currency)
    divisor = Decimal(str(entry[1])) if entry else Decimal("1")
    return (amount / divisor) / Decimal(str(rate))


# ---------------------------------------------------------------------------
# Public refresh API
# ---------------------------------------------------------------------------

def refresh_quote(
    conn: sqlite3.Connection,
    instrument_id: int,
    ticker: str,
    *,
    provider: PriceProvider = _default_provider,
    force: bool = False,
) -> dict:
    """Fetch the latest quote for one instrument.

    Returns {"price": Decimal, "currency": str, "date": str, "stale": bool}.
    Falls back to stale cached data on failure.
    """
    today = str(date.today())
    cached = get_cached_price(conn, instrument_id)
    if not force and cached and cached["date"] == today and not _is_quote_stale(cached["fetched_at"]):
        return cached

    quote = provider.get_quote(ticker)
    if quote and quote.get("price"):
        price_eur = _to_eur(float(quote["price"]), quote.get("currency", "EUR"))
        if math.isfinite(price_eur):
            _store_price(conn, instrument_id, today, price_eur, "EUR")
            conn.commit()
            return {
                "price": Decimal(str(price_eur)),
                "currency": "EUR",
                "date": today,
                "stale": False,
            }

    # Fall back to cache
    if cached:
        cached["stale"] = True
        return cached
    return {"price": None, "currency": "EUR", "date": today, "stale": True}


def refresh_recent(
    conn: sqlite3.Connection,
    instrument_id: int,
    ticker: str,
    period: str = "1y",
    *,
    provider: PriceProvider = _default_provider,
) -> list[dict]:
    """Fetch recent price history using a period string and cache it.

    Prices are converted to EUR before storing so that all arithmetic
    (avg_cost from value_eur vs current_price) is in a single currency.
    """
    # Skip if already fetched today
    latest = conn.execute(
        "SELECT fetched_at FROM prices WHERE instrument_id=? ORDER BY date DESC LIMIT 1",
        (instrument_id,),
    ).fetchone()
    if latest and not _is_history_stale(latest["fetched_at"]):
        rows = conn.execute(
            "SELECT date, close, currency FROM prices WHERE instrument_id=? ORDER BY date",
            (instrument_id,),
        ).fetchall()
        return [{"date": r["date"], "close": Decimal(r["close"]), "currency": r["currency"]}
                for r in rows]

    rows_fetched = provider.get_recent(ticker, period=period)
    for h in rows_fetched:
        close_eur = _to_eur(float(h["close"]), h["currency"])
        _store_price(conn, instrument_id, h["date"], close_eur, "EUR")
    if rows_fetched:
        conn.commit()

    rows = conn.execute(
        "SELECT date, close, currency FROM prices WHERE instrument_id=? ORDER BY date",
        (instrument_id,),
    ).fetchall()
    return [{"date": r["date"], "close": Decimal(r["close"]), "currency": r["currency"]}
            for r in rows]


def refresh_history(
    conn: sqlite3.Connection,
    instrument_id: int,
    ticker: str,
    start: str,
    end: str | None = None,
    *,
    provider: PriceProvider = _default_provider,
    force: bool = False,
) -> list[dict]:
    """Fetch and cache historical closes by date range. Converts to EUR.

    Skips the actual fetch (serves from cache) if we already fetched
    recently AND the cache already covers back to `start` — so a wider
    `start` than what's cached still triggers a real backfill even within
    the same day, unless `force` explicitly demands a re-fetch regardless.
    """
    if end is None:
        end = str(date.today())

    cached_range = conn.execute(
        "SELECT MIN(date) AS earliest, MAX(fetched_at) AS fetched_at "
        "FROM prices WHERE instrument_id=?",
        (instrument_id,),
    ).fetchone()
    has_enough_history = bool(cached_range and cached_range["earliest"] and cached_range["earliest"] <= start)
    is_fresh = bool(cached_range and cached_range["fetched_at"] and not _is_history_stale(cached_range["fetched_at"]))
    if not force and has_enough_history and is_fresh:
        rows = conn.execute(
            "SELECT date, close, currency FROM prices "
            "WHERE instrument_id=? AND date>=? AND date<=? ORDER BY date",
            (instrument_id, start, end),
        ).fetchall()
        return [{"date": r["date"], "close": Decimal(r["close"]), "currency": r["currency"]}
                for r in rows]

    history = provider.get_history(ticker, start, end)
    for h in history:
        close_eur = _to_eur(float(h["close"]), h["currency"])
        _store_price(conn, instrument_id, h["date"], close_eur, "EUR")
    if history:
        conn.commit()

    rows = conn.execute(
        "SELECT date, close, currency FROM prices "
        "WHERE instrument_id=? AND date>=? AND date<=? ORDER BY date",
        (instrument_id, start, end),
    ).fetchall()
    return [{"date": r["date"], "close": Decimal(r["close"]), "currency": r["currency"]}
            for r in rows]


def refresh_instrument_info(
    conn: sqlite3.Connection,
    instrument_id: int,
    ticker: str,
    *,
    provider: PriceProvider = _default_provider,
) -> bool:
    """Fetch sector/region/asset_type metadata and save to instruments row.

    Only updates fields that are currently NULL (manual overrides are never
    touched because the user set them explicitly).
    Returns True if any field was updated.
    """
    info = provider.get_info(ticker)
    if not info:
        return False

    inst = conn.execute(
        "SELECT sector, region, asset_type, currency FROM instruments WHERE id=?",
        (instrument_id,),
    ).fetchone()
    if not inst:
        return False

    updates: list[tuple[str, str]] = []
    sector_value = info.get("sector") or info.get("category")
    if not inst["sector"] and sector_value:
        updates.append(("sector", sector_value))
    if not inst["region"] and info.get("country"):
        updates.append(("region", info["country"]))
    if (not inst["asset_type"] or inst["asset_type"] == "other") and info.get("asset_type"):
        updates.append(("asset_type", info["asset_type"]))
    # Always sync currency from yfinance — the ticker may have changed (e.g. ULVR.L→UNA.AS)
    # so the stored currency ("GBP") may no longer match the new ticker's currency ("EUR").
    if info.get("currency") and info["currency"] != inst["currency"]:
        updates.append(("currency", info["currency"]))

    if not updates:
        return False

    set_clause = ", ".join(f"{col}=?" for col, _ in updates)
    values = [v for _, v in updates] + [instrument_id]
    conn.execute(f"UPDATE instruments SET {set_clause} WHERE id=?", values)
    conn.commit()
    return True


_FUND_DATA_TTL_DAYS = 7  # composition changes slowly — no need to refetch daily


def _is_fund_data_stale(fetched_at: str) -> bool:
    try:
        ts = datetime.fromisoformat(fetched_at)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts) > timedelta(days=_FUND_DATA_TTL_DAYS)
    except Exception:
        return True


def refresh_fund_data(
    conn: sqlite3.Connection,
    instrument_id: int,
    ticker: str,
    *,
    provider: PriceProvider = _default_provider,
    force: bool = False,
) -> bool:
    """Fetch and cache ETF/fund composition (asset classes, sector
    weightings, top holdings, equity metrics).

    Skips the fetch when already cached and fresh (fund composition changes
    slowly, unlike prices) unless force=True. Returns True if new data was
    fetched and stored — False if skipped (fresh, or not a fund / no data).
    """
    if not force:
        row = conn.execute(
            "SELECT fetched_at FROM fund_data WHERE instrument_id=?", (instrument_id,)
        ).fetchone()
        if row and not _is_fund_data_stale(row["fetched_at"]):
            return False

    data = provider.get_fund_data(ticker)
    if not data:
        return False

    conn.execute(
        """INSERT INTO fund_data
               (instrument_id, asset_classes, sector_weightings, top_holdings, equity_metrics, fetched_at)
               VALUES (?,?,?,?,?,?)
           ON CONFLICT(instrument_id) DO UPDATE SET
               asset_classes=excluded.asset_classes,
               sector_weightings=excluded.sector_weightings,
               top_holdings=excluded.top_holdings,
               equity_metrics=excluded.equity_metrics,
               fetched_at=excluded.fetched_at""",
        (
            instrument_id,
            json.dumps(data["asset_classes"]),
            json.dumps(data["sector_weightings"]),
            json.dumps(data["top_holdings"]),
            json.dumps(data["equity_metrics"]),
            _now_utc(),
        ),
    )
    conn.commit()
    return True


def get_fund_data_cached(conn: sqlite3.Connection, instrument_id: int) -> Optional[dict]:
    """Return cached ETF/fund composition data for an instrument, or None
    if never fetched (e.g. it's a stock, or fetch failed/found nothing)."""
    row = conn.execute(
        "SELECT asset_classes, sector_weightings, top_holdings, equity_metrics, fetched_at "
        "FROM fund_data WHERE instrument_id=?", (instrument_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "asset_classes": json.loads(row["asset_classes"] or "{}"),
        "sector_weightings": json.loads(row["sector_weightings"] or "{}"),
        "top_holdings": json.loads(row["top_holdings"] or "[]"),
        "equity_metrics": json.loads(row["equity_metrics"] or "{}"),
        "fetched_at": row["fetched_at"],
    }


def refresh_all_prices(
    conn: sqlite3.Connection,
    *,
    provider: PriceProvider = _default_provider,
    period: str = "5d",
) -> dict:
    """Refresh prices for all instruments that have a symbol mapped.

    Uses individual yf.Ticker().history() calls with a shared curl_cffi
    Chrome session to bypass Yahoo Finance bot-detection on server IPs.
    yf.download() is intentionally avoided — it has a known bug where a
    single problematic ticker crashes the entire batch.

    - No cached history yet, or cache doesn't reach back to the instrument's
      first transaction: fetches from that first-transaction date (so the
      value-over-time chart can show the account's full history, not just
      the last year).
    - Otherwise: uses `period` (default '5d') for a quick incremental
      refresh. Fresh data (<24h old) is skipped entirely.

    Returns {"refreshed": N, "failed": list[ticker]}.
    """
    import sys
    import time
    import yfinance as yf

    rows = conn.execute(
        "SELECT id, symbol FROM instruments WHERE symbol IS NOT NULL AND symbol != ''"
    ).fetchall()

    # Filter out clearly invalid symbols before even trying
    to_fetch: list[tuple[int, str, str | None]] = []  # (iid, ticker, start_date|None)
    skipped = 0
    for row in rows:
        iid, ticker = row["id"], row["symbol"]
        if not ticker or not ticker.strip():
            continue

        first_txn = conn.execute(
            "SELECT MIN(ts) AS ts FROM transactions WHERE instrument_id=?", (iid,)
        ).fetchone()
        desired_start = first_txn["ts"][:10] if first_txn and first_txn["ts"] else None

        cached = conn.execute(
            "SELECT MIN(date) AS earliest, MAX(fetched_at) AS fetched_at "
            "FROM prices WHERE instrument_id=?", (iid,)
        ).fetchone()
        has_full_history = bool(
            cached and cached["earliest"] and desired_start and cached["earliest"] <= desired_start
        )

        if not cached or not cached["earliest"]:
            to_fetch.append((iid, ticker, desired_start))  # no data at all
        elif not has_full_history:
            to_fetch.append((iid, ticker, desired_start))  # backfill missing older history
        elif _is_history_stale(cached["fetched_at"]):
            to_fetch.append((iid, ticker, None))  # just an incremental refresh
        else:
            skipped += 1

    try:
        import curl_cffi  # noqa: F401
        cffi_available = True
    except ImportError:
        cffi_available = False

    print(
        f"[price-refresh] {len(to_fetch)} to fetch, {skipped} fresh — "
        f"curl_cffi {'available (auto-detected by yfinance)' if cffi_available else 'NOT installed'}",
        file=sys.stderr, flush=True,
    )

    refreshed = 0
    failed: list[str] = []

    for i, (iid, ticker, start_date) in enumerate(to_fetch):
        print(
            f"[price-refresh] [{i+1}/{len(to_fetch)}] {ticker} "
            f"{'start=' + start_date if start_date else 'period=' + period}",
            file=sys.stderr, flush=True,
        )
        try:
            # Do NOT pass session= to yf.Ticker — curl_cffi is auto-detected by
            # yfinance internally; passing it manually causes 'str has no attr name'
            t = yf.Ticker(ticker)
            if start_date:
                df = t.history(start=start_date, auto_adjust=True)
            else:
                df = t.history(period=period, auto_adjust=True)
            if df is None or df.empty:
                print(f"[price-refresh]   {ticker}: empty dataframe", file=sys.stderr, flush=True)
                failed.append(ticker)
            else:
                # Get the currency yfinance actually reports for this ticker.
                # NOTE: this may be "GBp" (pence) for LSE stocks or "USD" for
                # US stocks — we convert everything to EUR before storing so
                # that avg_cost (from value_eur, always EUR) and current_price
                # are always in the same unit.
                try:
                    yf_currency = t.fast_info.currency or "EUR"
                except Exception:
                    yf_currency = "EUR"

                # Normalise display currency (GBp → GBP for instruments table)
                display_currency = "GBP" if yf_currency == "GBp" else yf_currency

                # Keep instrument.currency in sync with native currency (for display)
                conn.execute(
                    "UPDATE instruments SET currency=? WHERE id=? AND (currency IS NULL OR currency != ?)",
                    (display_currency, iid, display_currency),
                )

                # Convert each historical close to EUR
                fx_note = ""
                if yf_currency != "EUR":
                    # Force FX cache population so we see the rate in the log
                    cache_key = "GBP" if yf_currency == "GBp" else yf_currency
                    if cache_key not in _fx_rate_cache:
                        _fx_rate_cache[cache_key] = _fetch_eur_rate_from_yf(yf_currency)
                    rate = _fx_rate_cache.get(cache_key)
                    fx_note = f" fx:{yf_currency}→EUR rate={rate:.4f}" if rate else f" fx:{yf_currency}→EUR FAILED (native stored)"

                for idx, row in df.iterrows():
                    close_eur = _to_eur(float(row["Close"]), yf_currency)
                    _store_price(conn, iid, str(idx.date()), close_eur, "EUR")
                conn.commit()
                latest_date = df.index[-1].date()
                print(
                    f"[price-refresh]   {ticker}: {len(df)} rows, latest={latest_date}{fx_note}",
                    file=sys.stderr, flush=True,
                )
                refreshed += 1
        except Exception as exc:
            print(f"[price-refresh]   {ticker}: exception: {exc}", file=sys.stderr, flush=True)
            failed.append(ticker)

        if i < len(to_fetch) - 1:
            time.sleep(0.5)

    print(
        f"[price-refresh] done: refreshed={refreshed}, failed={failed}",
        file=sys.stderr, flush=True,
    )
    return {"refreshed": refreshed, "failed": failed}


# ---------------------------------------------------------------------------
# ISIN → ticker lookup
# ---------------------------------------------------------------------------

# DeGiro exchange names (Beurs column) → yfinance suffix
_DEGIRO_EXCH_SUFFIX: dict[str, str] = {
    "NSC":  ".AS",  # Euronext Amsterdam
    "XAMS": ".AS",
    "AMS":  ".AS",
    "EAM":  ".AS",
    "XET":  ".DE",  # Xetra
    "XETR": ".DE",
    "GER":  ".DE",
    "EPA":  ".PA",  # Euronext Paris
    "XPAR": ".PA",
    "MIL":  ".MI",  # Borsa Italiana
    "XMIL": ".MI",
    "BME":  ".MC",  # Madrid
    "SWX":  ".SW",  # Swiss
    "XSWX": ".SW",
    "OSL":  ".OL",  # Oslo
    "XOSL": ".OL",
    "STO":  ".ST",  # Stockholm
    "XSTO": ".ST",
    "CPH":  ".CO",  # Copenhagen
    "XCSE": ".CO",
    "HEL":  ".HE",  # Helsinki
    "XHEL": ".HE",
    "BRU":  ".BR",  # Euronext Brussels
    "XBRU": ".BR",
    "LSE":  ".L",   # London
    "XLON": ".L",
    "NSY":  "",     # NYSE
    "NYSE": "",
    "NGS":  "",     # Nasdaq
    "XNAS": "",
    "XNGS": "",
}

# OpenFIGI exchCode → yfinance suffix
_FIGI_EXCH_SUFFIX: dict[str, str] = {
    "NA": ".AS", "GY": ".DE", "LN": ".L",  "FP": ".PA",
    "IM": ".MI", "SM": ".MC", "SW": ".SW", "SS": ".ST",
    "BB": ".BR", "DC": ".CO", "HO": ".HE", "NO": ".OL",
    "PW": ".WA", "UN": "",   "UW": "",    "UA": "",
}


# ---------------------------------------------------------------------------
# ISIN → ticker lookup
# ---------------------------------------------------------------------------
_DEGIRO_EXCH_SUFFIX: dict[str, str] = {
    "NSC":  ".AS",  # Euronext Amsterdam
    "XAMS": ".AS",
    "AMS":  ".AS",
    "EAM":  ".AS",
    "XET":  ".DE",  # Xetra
    "XETR": ".DE",
    "GER":  ".DE",
    "EPA":  ".PA",  # Euronext Paris
    "XPAR": ".PA",
    "MIL":  ".MI",  # Borsa Italiana
    "XMIL": ".MI",
    "BME":  ".MC",  # Madrid
    "SWX":  ".SW",  # Swiss
    "XSWX": ".SW",
    "OSL":  ".OL",  # Oslo
    "XOSL": ".OL",
    "STO":  ".ST",  # Stockholm
    "XSTO": ".ST",
    "CPH":  ".CO",  # Copenhagen
    "XCSE": ".CO",
    "HEL":  ".HE",  # Helsinki
    "XHEL": ".HE",
    "BRU":  ".BR",  # Euronext Brussels
    "XBRU": ".BR",
    "LSE":  ".L",   # London
    "XLON": ".L",
    "NSY":  "",     # NYSE
    "NYSE": "",
    "NGS":  "",     # Nasdaq
    "XNAS": "",
    "XNGS": "",
}

# Priority per ISIN country code — first exchange with data wins.
# DeGiro users trade primarily on Amsterdam/Euronext even for GB-ISIN stocks
# (e.g. Unilever GB00BVZK7T90 = UNA.AS, not ULVR.L). So EU priority applies
# to all non-US ISINs; validation will skip candidates with no data.
_FIGI_PRIORITY_US = ["UN", "UW", "UA", "NA", "GY", "LN", "FP", "IM",
                     "SM", "SW", "SS", "BB", "DC", "HO", "NO", "PW"]
_FIGI_PRIORITY_EU = ["NA", "GY", "LN", "FP", "IM", "SM", "SW", "SS",
                     "BB", "DC", "HO", "NO", "PW", "UN", "UW", "UA"]


def _openfigi_lookup(isin: str, timeout: int = 10) -> list:
    """Query OpenFIGI for an ISIN.

    Returns an ordered list of candidate ticker strings (best first).
    Priority is adjusted based on ISIN country code:
      US → US exchanges first
      GB → London first
      other → Amsterdam/Euronext first (typical DeGiro EU user)
    Empty list if nothing found or network error.
    """
    import json as _json
    import urllib.request

    if isin.startswith("US"):
        priority = _FIGI_PRIORITY_US
    else:
        priority = _FIGI_PRIORITY_EU

    url = "https://api.openfigi.com/v3/mapping"
    body = _json.dumps([{"idType": "ID_ISIN", "idValue": isin}]).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = _json.loads(resp.read().decode())
    except Exception as exc:
        print(f"[openfigi] request failed for {isin}: {exc}", file=__import__('sys').stderr, flush=True)
        return []

    if not data or not isinstance(data, list):
        return []
    entry = data[0]
    if "error" in entry:
        print(f"[openfigi] API error for {isin}: {entry['error']}", file=__import__('sys').stderr, flush=True)
        return []
    if "data" not in entry or not entry["data"]:
        return []

    candidates = entry["data"]
    seen: set = set()
    result = []

    # Priority-ordered pass
    for exch_code in priority:
        suffix = _FIGI_EXCH_SUFFIX[exch_code]
        for c in candidates:
            if c.get("exchCode") == exch_code and c.get("ticker"):
                t = c["ticker"] + suffix
                if t not in seen:
                    seen.add(t)
                    result.append(t)

    # Catch-all: any remaining candidates
    for c in candidates:
        ticker = c.get("ticker", "")
        exch   = c.get("exchCode", "")
        if ticker:
            t = ticker + _FIGI_EXCH_SUFFIX.get(exch, "")
            if t not in seen:
                seen.add(t)
                result.append(t)

    return result[:15]


def _ticker_validate(ticker: str, timeout: int = 12) -> tuple:
    """Validate a ticker with yfinance. Returns (valid: bool, reason: str).

    Tries multiple methods in order of speed:
    1. fast_info.last_price (fastest, but None outside market hours)
    2. 5-day history window (reliable but slower)
    Both run in a sub-thread with timeout to avoid hanging.
    """
    import threading as _thr

    result: list = [(False, "timeout")]

    def _do():
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)

            # Method 1: fast_info (instant if cached)
            try:
                fi = t.fast_info
                price = fi.last_price
                if price and price > 0:
                    result[0] = (True, f"fast_info price={price:.2f}")
                    return
            except Exception:
                pass

            # Method 2: try to get any recent history
            from datetime import date, timedelta
            end   = str(date.today())
            start = str(date.today() - timedelta(days=7))
            df = t.history(start=start, end=end, auto_adjust=True)
            if df is not None and not df.empty:
                result[0] = (True, f"history rows={len(df)}")
                return

            # Method 3: check if info has a regularMarketPrice
            info = t.info or {}
            price2 = info.get("regularMarketPrice") or info.get("previousClose")
            if price2 and price2 > 0:
                result[0] = (True, f"info price={price2}")
                return

            result[0] = (False, "no data found")
        except Exception as exc:
            result[0] = (False, f"exception: {exc}")

    t = _thr.Thread(target=_do, daemon=True)
    t.start()
    t.join(timeout=timeout)
    return result[0]


def lookup_ticker_by_isin(
    isin: str,
    exchange=None,
    provider=None,
):
    """Find a yfinance-compatible ticker for an ISIN via OpenFIGI.

    Returns the best candidate from OpenFIGI, validated against yfinance.
    Tries candidates in priority order and returns the first one that actually
    has price data. Returns None if no working ticker is found.
    """
    import sys
    import yfinance as yf

    candidates = _openfigi_lookup(isin)
    if not candidates:
        return None

    print(f"[ticker-mapper]   OpenFIGI candidates ({len(candidates)}): {candidates[:8]}", file=sys.stderr, flush=True)

    for ticker in candidates:
        if not ticker or not ticker.strip():
            continue
        try:
            # Do NOT pass session= to yf.Ticker — curl_cffi is auto-detected
            # by yfinance; passing it manually causes 'str has no attr name'
            t = yf.Ticker(ticker)
            df = t.history(period="5d", auto_adjust=True)
            if df is not None and not df.empty:
                print(f"[ticker-mapper]   validated: {ticker}", file=sys.stderr, flush=True)
                return ticker
            else:
                print(f"[ticker-mapper]   {ticker}: no data, trying next", file=sys.stderr, flush=True)
        except Exception as exc:
            print(f"[ticker-mapper]   {ticker}: exception: {exc}", file=sys.stderr, flush=True)

    print(f"[ticker-mapper]   all candidates failed for {isin}", file=sys.stderr, flush=True)
    return None


def auto_map_tickers(
    conn: sqlite3.Connection,
    *,
    provider=None,
    fetch_history: bool = True,
    history_start: str = "2010-01-01",
) -> dict:
    """For all instruments with an ISIN but no ticker, look up the ticker via
    OpenFIGI and immediately fetch price history and metadata.

    Returns {"mapped": N, "failed": list[str], "already_mapped": N}.
    """
    import time

    if provider is None:
        provider = _default_provider

    unmapped = conn.execute(
        "SELECT id, isin, name, exchange FROM instruments "
        "WHERE isin IS NOT NULL AND isin != '' AND (symbol IS NULL OR symbol = '')"
    ).fetchall()

    mapped = 0
    failed = []
    already_mapped = conn.execute(
        "SELECT COUNT(*) AS n FROM instruments WHERE symbol IS NOT NULL AND symbol != ''"
    ).fetchone()["n"]

    for i, row in enumerate(unmapped):
        isin          = row["isin"]
        instrument_id = row["id"]
        name          = row["name"] or isin

        # Rate-limit: OpenFIGI allows ~6 req/min without API key
        if i > 0:
            time.sleep(1.0)

        ticker = lookup_ticker_by_isin(isin, exchange=row["exchange"], provider=provider)
        if not ticker:
            failed.append(f"{name} ({isin})")
            continue

        # Save ticker
        conn.execute("UPDATE instruments SET symbol=? WHERE id=?", (ticker, instrument_id))
        conn.commit()
        mapped += 1

        # Fetch metadata and full history
        refresh_instrument_info(conn, instrument_id, ticker, provider=provider)
        if fetch_history:
            refresh_history(conn, instrument_id, ticker,
                            start=history_start, provider=provider)

    return {"mapped": mapped, "failed": failed, "already_mapped": already_mapped}
