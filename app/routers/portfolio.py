"""Dashboard, holdings, and instrument detail routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

import sys
import threading
import json as _json
from datetime import date
from decimal import Decimal, InvalidOperation

from ..db import get_db, get_setting, set_setting, _open as _db_open
from ..helpers import templates, require_auth, optional_account_id
from ..services import portfolio as svc_portfolio
from ..services import prices as svc_prices

router = APIRouter(tags=["portfolio"])


# ---------------------------------------------------------------------------
# Background: ticker mapping
# ---------------------------------------------------------------------------

def _ticker_map_run() -> None:
    """Module-level daemon thread: map ISINs to yfinance tickers."""
    import time

    _LOG_FILE = "/tmp/ticker-mapper.log"

    def _log(msg: str) -> None:
        line = f"[ticker-mapper] {msg}"
        print(line, file=sys.stderr, flush=True)
        try:
            with open(_LOG_FILE, "a") as _f:
                _f.write(line + "\n")
        except Exception:
            pass

    conn = None
    try:
        _log("thread started")
        conn = _db_open()
        _log("db opened")

        unmapped = conn.execute(
            "SELECT id, isin, name, exchange FROM instruments "
            "WHERE isin IS NOT NULL AND isin != '' "
            "AND (symbol IS NULL OR symbol = '')"
        ).fetchall()

        _log(f"{len(unmapped)} unmapped instrument(s) found")
        set_setting(conn, "ticker_map_progress", f"0/{len(unmapped)} verwerkt")
        conn.commit()

        mapped = 0
        failed = []

        for i, row in enumerate(unmapped):
            isin = row["isin"]
            name = row["name"] or isin
            iid  = row["id"]

            _log(f"[{i + 1}/{len(unmapped)}] looking up {isin} ({name})")
            set_setting(conn, "ticker_map_progress",
                        f"{i + 1}/{len(unmapped)}: {name}")
            conn.commit()

            if i > 0:
                time.sleep(1.2)  # stay under OpenFIGI rate limit

            ticker = None
            try:
                candidates = svc_prices._openfigi_lookup(isin)
                _log(f"  OpenFIGI candidates: {candidates[:5]}")
                # Take the first candidate directly — OpenFIGI is reliable enough.
                # Skipping yfinance validation because Yahoo Finance rate-limits
                # server IPs aggressively. Prices will be fetched later.
                if candidates:
                    ticker = candidates[0]
            except Exception as e:
                _log(f"  lookup error: {e}")

            if ticker:
                _log(f"  {isin} → {ticker} ✓")
                conn.execute(
                    "UPDATE instruments SET symbol=? WHERE id=?",
                    (ticker, iid))
                conn.commit()
                mapped += 1
                try:
                    svc_prices.refresh_instrument_info(conn, iid, ticker)
                except Exception as e:
                    _log(f"  info fetch failed: {e}")
                try:
                    # Fetch last year of daily closes — fast, works outside market hours
                    result = svc_prices.refresh_recent(conn, iid, ticker, period="1y")
                    _log(f"  prices fetched: {len(result)} rows for {ticker}")
                except Exception as e:
                    _log(f"  price fetch failed: {e}")
                try:
                    # ETF/fund composition (sector weightings, top holdings,
                    # asset classes) — no-op for individual stocks.
                    got_fund_data = svc_prices.refresh_fund_data(conn, iid, ticker)
                    _log(f"  fund data: {'fetched' if got_fund_data else 'none/skipped'} for {ticker}")
                except Exception as e:
                    _log(f"  fund data fetch failed: {e}")
            else:
                _log(f"  {isin} → not found")
                failed.append(f"{name} ({isin})")

        result = {
            "mapped": mapped,
            "failed": failed,
            "already_mapped": conn.execute(
                "SELECT COUNT(*) AS n FROM instruments "
                "WHERE symbol IS NOT NULL AND symbol != ''"
            ).fetchone()["n"],
        }
        _log(f"done — mapped={mapped} failed={len(failed)}")
        set_setting(conn, "ticker_map_status", "done")
        set_setting(conn, "ticker_map_result", _json.dumps(result))
        set_setting(conn, "ticker_map_progress", f"Klaar: {mapped} gekoppeld")
        conn.commit()

    except BaseException as exc:
        import traceback as _tb
        _log(f"FATAL: {exc}\n{_tb.format_exc()}")
        if conn:
            try:
                set_setting(conn, "ticker_map_status", "error")
                set_setting(conn, "ticker_map_result", str(exc))
                conn.commit()
            except Exception:
                pass
    finally:
        if conn:
            conn.close()


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def _stock_dashboard_context(conn, account_id: int | None = None) -> dict:
    summary = svc_portfolio.get_portfolio_summary(conn, account_id=account_id)
    allocation = svc_portfolio.get_allocation(conn, account_id=account_id)
    allocation_details = svc_portfolio.get_allocation_details(conn, account_id=account_id)
    holdings = svc_portfolio.get_holdings(conn, account_id=account_id)

    from ..services.dividends import get_trailing_12m_income, get_dividend_events, get_dividend_events_detail
    trailing = get_trailing_12m_income(conn, account_id=account_id)
    dividend_events = get_dividend_events(conn, account_id=account_id)
    dividend_events_detail = get_dividend_events_detail(conn, account_id=account_id)

    # Portfolio value series — full history; the range selector (1M/YTD/1J/
    # Custom/Alles) filters this client-side, along with the realized P/L,
    # dividend events, and per-holding series below, so every range-dependent
    # number on the dashboard (not just the chart) can be recomputed without
    # a server round-trip.
    value_series = svc_portfolio.get_portfolio_value_series(conn, account_id=account_id)
    realized_events = svc_portfolio.get_realized_pl_events(conn, account_id=account_id)
    fee_events = svc_portfolio.get_fee_events(conn, account_id=account_id)
    holdings_value_series = svc_portfolio.get_holdings_value_series(conn, account_id=account_id)

    # Unrealized P/L over time (value minus running avg-cost, no cash) for
    # the "Ongerealiseerd" stat — naturally immune to deposits/cash-snapshot
    # jumps and to simply buying more (see get_unrealized_pl_series docstring).
    unrealized_series = svc_portfolio.get_unrealized_pl_series(conn, account_id=account_id)
    return {
        "summary": summary,
        "allocation": allocation,
        "allocation_details": allocation_details,
        "holdings": holdings,
        "trailing_12m_income": trailing,
        "value_series": value_series,
        "realized_events": realized_events,
        "fee_events": fee_events,
        "dividend_events": dividend_events,
        "dividend_events_detail": dividend_events_detail,
        "unrealized_series": unrealized_series,
        "holdings_value_series": holdings_value_series,
        "accounts": [acc for acc in svc_portfolio.list_accounts(conn) if acc.type in ("broker", "pension")],
        "selected_account": account_id,
        "include_in_dashboard": get_setting(conn, "include_stocks_in_dashboard", "1") != "0",
    }


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, conn=Depends(get_db), _=Depends(require_auth)):
    from ..services.bitvavo import crypto_overview
    from ..services.savings import savings_accounts, savings_value_series

    show_stocks = get_setting(conn, "include_stocks_in_dashboard", "1") != "0"
    # Crypto is synced from Bitvavo and intentionally excluded from portable
    # database backups. Do not render an empty crypto card after a restore;
    # it returns automatically after a fresh synchronization.
    has_crypto_data = conn.execute(
        "SELECT 1 FROM crypto_balances UNION SELECT 1 FROM crypto_transactions LIMIT 1"
    ).fetchone() is not None
    show_crypto = get_setting(conn, "include_crypto_in_dashboard", "1") != "0" and has_crypto_data
    stock_summary = svc_portfolio.get_portfolio_summary(conn) if show_stocks else None
    crypto = crypto_overview(conn) if show_crypto else None
    dashboard_savings = savings_accounts(conn, include_hidden=False)
    savings_series = savings_value_series(conn, include_hidden=False)
    stock_value_series = svc_portfolio.get_portfolio_value_series(conn) if show_stocks else []
    savings_balance = sum((item["balance"] for item in dashboard_savings), Decimal("0"))
    savings_interest = sum((item["interest"] for item in dashboard_savings), Decimal("0"))
    interest_since_dates = [
        item["interest_since"] for item in dashboard_savings if item.get("interest_since")
    ]
    savings_interest_since = (
        date.fromisoformat(min(interest_since_dates)).strftime("%d-%m-%Y")
        if interest_since_dates else None
    )
    total_value = (
        (stock_summary["total_value"] if stock_summary else Decimal("0"))
        + (crypto["total"] if crypto else Decimal("0"))
        + savings_balance
    )
    total_result = (
        (stock_summary["total_pl"] if stock_summary else Decimal("0"))
        + (crypto["unrealized_result"] if crypto else Decimal("0"))
        + savings_interest
    )
    return templates.TemplateResponse("overview_dashboard.html", {
        "request": request,
        "show_stocks": show_stocks,
        "show_crypto": show_crypto,
        "stock_summary": stock_summary,
        "crypto": crypto,
        "dashboard_savings": dashboard_savings,
        "savings_balance": savings_balance,
        "savings_interest": savings_interest,
        "savings_interest_since": savings_interest_since,
        "total_value": total_value,
        "total_result": total_result,
        "overview_series": {
            "stocks": stock_value_series,
            "crypto": crypto["value_series"] if crypto else [],
            "savings": savings_series,
        },
    })


@router.get("/stocks", response_class=HTMLResponse)
async def stocks_dashboard(
    request: Request,
    account: int | None = Depends(optional_account_id),
    conn=Depends(get_db),
    _=Depends(require_auth),
):
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        **_stock_dashboard_context(conn, account_id=account),
    })


@router.post("/stocks/visibility")
async def set_stocks_visibility(
    include_in_dashboard: int = Form(0),
    account: int | None = Depends(optional_account_id),
    conn=Depends(get_db),
    _=Depends(require_auth),
):
    set_setting(conn, "include_stocks_in_dashboard", "1" if include_in_dashboard else "0")
    suffix = f"?account={account}" if account is not None else ""
    return RedirectResponse(url=f"/stocks{suffix}", status_code=303)


# ---------------------------------------------------------------------------
# Holdings
# ---------------------------------------------------------------------------

@router.get("/holdings", response_class=HTMLResponse)
async def holdings_page(
    request: Request,
    account: int | None = Depends(optional_account_id),
    sort: str = "value",
    conn=Depends(get_db),
    _=Depends(require_auth),
):
    holdings = svc_portfolio.get_holdings(conn, account_id=account)
    # Sort
    key_map = {
        "name": lambda h: h.instrument.name,
        "value": lambda h: -(h.current_value or 0),
        "pl": lambda h: -(h.unrealized_pl or 0),
        "pl_pct": lambda h: -(h.unrealized_pl_pct or 0),
        "qty": lambda h: -(h.quantity),
    }
    holdings.sort(key=key_map.get(sort, key_map["value"]))
    closed = svc_portfolio.get_closed_positions(conn, account_id=account)
    # Savings has its own dashboard and must not look like uninvested broker
    # cash on the holdings page.
    cash_balances = svc_portfolio.get_cash_balances(
        conn, account_id=account, include_savings=False
    )
    summary = svc_portfolio.get_portfolio_summary(conn, account_id=account)
    return templates.TemplateResponse("holdings.html", {
        "request": request,
        "holdings": holdings,
        "closed_positions": closed,
        "cash_balances": cash_balances,
        "total_account": summary["total_value"],
        "portfolio_value": summary["holdings_value"],
        "accounts": [acc for acc in svc_portfolio.list_accounts(conn) if acc.type in ("broker", "pension")],
        "selected_account": account,
        "sort": sort,
    })


# ---------------------------------------------------------------------------
# Instrument detail
# ---------------------------------------------------------------------------

def _instrument_context(request: Request, instrument_id: int, conn):
    """Shared data for the full instrument page and its compact side panel."""
    inst_row = conn.execute(
        "SELECT * FROM instruments WHERE id=?", (instrument_id,)
    ).fetchone()
    if not inst_row:
        return None

    transactions = conn.execute(
        """SELECT t.*, a.name AS account_name
           FROM transactions t JOIN accounts a ON a.id=t.account_id
           WHERE t.instrument_id=? ORDER BY t.ts DESC""",
        (instrument_id,),
    ).fetchall()
    dividends = conn.execute(
        """SELECT ce.*, a.name AS account_name
           FROM cash_events ce JOIN accounts a ON a.id=ce.account_id
           WHERE ce.instrument_id=? AND ce.type IN ('dividend','dividend_tax')
           ORDER BY ce.ts DESC""",
        (instrument_id,),
    ).fetchall()
    country_weights = [dict(r) for r in conn.execute(
        "SELECT country, weight_pct FROM instrument_country_weights "
        "WHERE instrument_id=? ORDER BY CAST(weight_pct AS REAL) DESC, country",
        (instrument_id,),
    ).fetchall()]

    return {
        "request": request,
        "instrument": dict(inst_row),
        "holdings": [h for h in svc_portfolio.get_holdings(conn) if h.instrument.id == instrument_id],
        "transactions": [dict(r) for r in transactions],
        "dividends": [dict(r) for r in dividends],
        "cached_price": svc_prices.get_cached_price(conn, instrument_id),
        "fund_data": svc_prices.get_fund_data_cached(conn, instrument_id),
        "country_weights": country_weights,
        "country_weight_total": sum((Decimal(row["weight_pct"]) for row in country_weights), Decimal("0")),
        "country_weight_error": request.query_params.get("country_weight_error"),
        "accounts": [dict(r) for r in conn.execute("SELECT id, name FROM accounts ORDER BY name").fetchall()],
    }


@router.get("/instrument/{instrument_id}", response_class=HTMLResponse)
async def instrument_detail(
    request: Request,
    instrument_id: int,
    conn=Depends(get_db),
    _=Depends(require_auth),
):
    context = _instrument_context(request, instrument_id, conn)
    if not context:
        return templates.TemplateResponse("error.html", {"request": request, "msg": "Not found"}, status_code=404)
    return templates.TemplateResponse("instrument.html", context)


@router.get("/instrument/{instrument_id}/panel", response_class=HTMLResponse)
async def instrument_panel(
    request: Request,
    instrument_id: int,
    conn=Depends(get_db),
    _=Depends(require_auth),
):
    context = _instrument_context(request, instrument_id, conn)
    if not context:
        return HTMLResponse("Not found", status_code=404)
    return templates.TemplateResponse("instrument_panel.html", context)


@router.post("/instrument/{instrument_id}/update")
async def instrument_update(
    request: Request,
    instrument_id: int,
    conn=Depends(get_db),
    _=Depends(require_auth),
):
    """Update ticker mapping, sector, region, asset_type overrides."""
    form = await request.form()
    fields = {}
    for col in ("symbol", "exchange", "sector", "region", "asset_type"):
        if col in form:
            val = str(form[col]).strip() or None
            fields[col] = val

    if fields:
        set_clause = ", ".join(f"{k}=?" for k in fields)
        values = list(fields.values()) + [instrument_id]
        conn.execute(f"UPDATE instruments SET {set_clause} WHERE id=?", values)

    # Manual annual dividend override
    if "manual_div_eur" in form:
        isin_row = conn.execute(
            "SELECT isin FROM instruments WHERE id=?", (instrument_id,)
        ).fetchone()
        if isin_row and isin_row["isin"]:
            val = str(form["manual_div_eur"]).strip()
            if val:
                set_setting(conn, f"div_annual_{isin_row['isin']}", val)

    return RedirectResponse(url=f"/instrument/{instrument_id}", status_code=303)


@router.post("/instrument/{instrument_id}/country-weights")
async def save_country_weight(
    request: Request,
    instrument_id: int,
    conn=Depends(get_db),
    _=Depends(require_auth),
):
    """Add or update one manually maintained ETF country weight."""
    form = await request.form()
    country = str(form.get("country", "")).strip()
    raw_weight = str(form.get("weight_pct", "")).strip().replace(",", ".")
    try:
        weight_pct = Decimal(raw_weight)
    except InvalidOperation:
        weight_pct = Decimal("0")

    if not country or not weight_pct.is_finite() or weight_pct <= 0 or weight_pct > 100:
        return RedirectResponse(
            url=f"/instrument/{instrument_id}?country_weight_error=invalid", status_code=303
        )

    current_rows = conn.execute(
        "SELECT weight_pct FROM instrument_country_weights WHERE instrument_id=? AND country != ?",
        (instrument_id, country),
    ).fetchall()
    current_total = sum((Decimal(row["weight_pct"]) for row in current_rows), Decimal("0"))
    if current_total + weight_pct > Decimal("100"):
        return RedirectResponse(
            url=f"/instrument/{instrument_id}?country_weight_error=total", status_code=303
        )

    conn.execute(
        """INSERT INTO instrument_country_weights(instrument_id, country, weight_pct)
           VALUES (?, ?, ?)
           ON CONFLICT(instrument_id, country) DO UPDATE SET weight_pct=excluded.weight_pct""",
        (instrument_id, country, str(weight_pct)),
    )
    return RedirectResponse(url=f"/instrument/{instrument_id}", status_code=303)


@router.post("/instrument/{instrument_id}/country-weights/delete")
async def delete_country_weight(
    request: Request,
    instrument_id: int,
    conn=Depends(get_db),
    _=Depends(require_auth),
):
    form = await request.form()
    country = str(form.get("country", "")).strip()
    if country:
        conn.execute(
            "DELETE FROM instrument_country_weights WHERE instrument_id=? AND country=?",
            (instrument_id, country),
        )
    return RedirectResponse(url=f"/instrument/{instrument_id}", status_code=303)


# ---------------------------------------------------------------------------
# Price refresh (AJAX)
# ---------------------------------------------------------------------------

@router.post("/api/refresh-prices")
async def api_refresh_prices(_=Depends(require_auth)):
    """Refresh prices for all mapped instruments.

    Runs synchronously in the thread pool so the actual result can be returned
    to the frontend. Uses period='5d' (fast); first-time fetch uses '1y'.
    """
    import asyncio
    loop = asyncio.get_event_loop()

    def _do_refresh() -> dict:
        c = None
        try:
            c = _db_open()
            result = svc_prices.refresh_all_prices(c, period="5d")
            print(f"[price-refresh] done: {result}", file=sys.stderr, flush=True)
            return result
        except Exception as exc:
            print(f"[price-refresh] error: {exc}", file=sys.stderr, flush=True)
            return {"refreshed": 0, "failed": [], "error": str(exc)}
        finally:
            if c:
                c.close()

    result = await loop.run_in_executor(None, _do_refresh)
    return JSONResponse(result)


@router.post("/api/auto-map-tickers")
async def api_auto_map_tickers(request: Request, _=Depends(require_auth)):
    """Start ticker mapping as a daemon thread; return immediately.
    Poll /api/auto-map-tickers/status for progress.
    Add ?force=1 to reset a stuck "running" status and restart.
    """
    force = request.query_params.get("force", "0") == "1"

    # Check if a thread with this name is already alive
    already_running = any(
        t.name == "ticker-mapper" and t.is_alive()
        for t in threading.enumerate()
    )
    if already_running and not force:
        return JSONResponse({"started": False, "reason": "already running"})

    # Mark as running before starting thread
    init = _db_open()
    set_setting(init, "ticker_map_status", "running")
    set_setting(init, "ticker_map_result", "")
    set_setting(init, "ticker_map_progress", "Opstarten…")
    init.commit()
    init.close()

    threading.Thread(target=_ticker_map_run, daemon=True, name="ticker-mapper").start()
    return JSONResponse({"started": True})


@router.get("/api/auto-map-tickers/status")
async def api_auto_map_status(conn=Depends(get_db), _=Depends(require_auth)):
    status   = get_setting(conn, "ticker_map_status")  or "idle"
    raw      = get_setting(conn, "ticker_map_result")  or ""
    progress = get_setting(conn, "ticker_map_progress") or ""
    result = None
    if raw:
        try:
            result = _json.loads(raw)
        except Exception:
            result = {"error": raw}
    return JSONResponse({"status": status, "result": result, "progress": progress})


@router.post("/api/reset-ticker-mapping")
async def api_reset_ticker_mapping(conn=Depends(get_db), _=Depends(require_auth)):
    """Clear all stored ticker symbols so auto-map-tickers will re-validate them.

    Useful after bad tickers (e.g. 'EU', '') were stored from a previous
    OpenFIGI lookup that skipped validation.
    """
    result = conn.execute(
        "UPDATE instruments SET symbol = NULL WHERE symbol IS NOT NULL"
    )
    conn.commit()
    count = result.rowcount
    print(f"[ticker-reset] cleared {count} ticker symbol(s)", file=sys.stderr, flush=True)
    return JSONResponse({"cleared": count})


async def api_manual_price(
    request: Request,
    instrument_id: int,
    conn=Depends(get_db),
    _=Depends(require_auth),
):
    form = await request.form()
    price_str = str(form.get("price", "")).strip()
    date_str = str(form.get("date", "")).strip()
    currency = str(form.get("currency", "EUR")).strip()
    if not price_str or not date_str:
        return JSONResponse({"error": "price and date required"}, status_code=400)
    from decimal import Decimal, InvalidOperation
    try:
        price = Decimal(price_str)
    except InvalidOperation:
        return JSONResponse({"error": "invalid price"}, status_code=400)
    if not price.is_finite() or price <= 0:
        return JSONResponse({"error": "price must be a positive number"}, status_code=400)
    conn.execute(
        """INSERT INTO prices(instrument_id, date, close, currency, fetched_at)
           VALUES (?,?,?,?,datetime('now'))
           ON CONFLICT(instrument_id, date) DO UPDATE
           SET close=excluded.close, fetched_at=excluded.fetched_at""",
        (instrument_id, date_str, str(price), currency),
    )
    return JSONResponse({"ok": True})


@router.post("/api/manual-transaction/{instrument_id}")
async def api_manual_transaction(
    request: Request,
    instrument_id: int,
    conn=Depends(get_db),
    _=Depends(require_auth),
):
    """Add a manual buy/sell/adjustment transaction for an instrument.

    Used to book corporate actions (splits, mergers) or correct import errors.
    """
    from decimal import Decimal, InvalidOperation

    form = await request.form()
    direction  = str(form.get("direction", "buy")).strip()   # "buy" or "sell"
    qty_str    = str(form.get("quantity", "")).strip().replace(",", ".")
    price_str  = str(form.get("price", "")).strip().replace(",", ".")
    date_str   = str(form.get("date", "")).strip()
    note       = str(form.get("note", "")).strip()[:200]
    account_id = form.get("account_id")

    if not qty_str or not price_str or not date_str or not account_id:
        return JSONResponse({"error": "quantity, price, date and account required"}, status_code=400)

    try:
        quantity = Decimal(qty_str)
        price    = Decimal(price_str)
        if direction == "sell":
            quantity = -abs(quantity)
        else:
            quantity = abs(quantity)
        value_eur = -(quantity * price)  # negative for buys, positive for sells
    except InvalidOperation:
        return JSONResponse({"error": "ongeldige hoeveelheid of prijs"}, status_code=400)

    ts = f"{date_str}T12:00:00"
    conn.execute(
        """INSERT OR IGNORE INTO transactions
           (account_id, instrument_id, ts, quantity, price, local_currency,
            fx_rate, value_eur, fees_eur, order_id, source)
           VALUES (?,?,?,?,?,'EUR',NULL,?,0,?,?)""",
        (account_id, instrument_id, ts, str(quantity), str(price),
         str(value_eur), f"manual:{note}" if note else "manual", "manual"),
    )
    conn.commit()
    return JSONResponse({"ok": True})
