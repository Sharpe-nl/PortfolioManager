"""Settings page."""
from __future__ import annotations

import asyncio
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

from ..auth import list_credentials
from ..db import get_db, get_setting, set_setting
from ..helpers import templates, require_auth
from ..services.bitvavo import BitvavoError, sync_bitvavo
from ..services.credentials import clear_bitvavo_credentials, has_bitvavo_credentials, save_bitvavo_credentials
from ..services.logo_cache import clear_missing_logo_cache
from ..services.refresh_scheduler import get_refresh_times, save_refresh_times
from ..services.updates import check_for_update, current_version, self_update_enabled, start_self_update

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_class=HTMLResponse)
async def settings_page(request: Request, conn=Depends(get_db), _=Depends(require_auth)):
    logo_dev_token_configured = bool(get_setting(conn, "logo_dev_token"))
    refresh_times = get_refresh_times(conn)

    unmapped = conn.execute(
        "SELECT id, name, isin FROM instruments WHERE symbol IS NULL OR symbol = '' ORDER BY name"
    ).fetchall()

    mapped = conn.execute(
        "SELECT id, name, isin, symbol FROM instruments "
        "WHERE symbol IS NOT NULL AND symbol != '' ORDER BY name"
    ).fetchall()

    txn_count  = conn.execute("SELECT COUNT(*) AS n FROM transactions").fetchone()["n"]
    inst_count = conn.execute("SELECT COUNT(*) AS n FROM instruments").fetchone()["n"]
    acct_count = conn.execute("SELECT COUNT(*) AS n FROM accounts").fetchone()["n"]

    return templates.TemplateResponse("settings.html", {
        "request": request,
        "logo_dev_token_configured": logo_dev_token_configured,
        "bitvavo_configured": has_bitvavo_credentials(conn),
        "refresh_time_1": refresh_times[0],
        "refresh_time_2": refresh_times[1] if len(refresh_times) > 1 else refresh_times[0],
        "refresh_last_run": get_setting(conn, "automatic_refresh_last_run"),
        "server_timezone": datetime.now().astimezone().tzname() or "local",
        "app_version": current_version(),
        "self_update_enabled": self_update_enabled(),
        "webauthn_credentials": list_credentials(conn),
        "unmapped_instruments": [dict(r) for r in unmapped],
        "mapped_instruments": [dict(r) for r in mapped],
        "db_counts": {
            "transactions": txn_count,
            "instruments": inst_count,
            "accounts": acct_count,
        },
    })


@router.post("/check-update")
async def check_update(_=Depends(require_auth)):
    """Check the immutable public version marker without delaying the event loop."""
    result = await asyncio.to_thread(check_for_update)
    if result["error"]:
        return RedirectResponse(url="/settings?update=check_error", status_code=303)
    if result["update_available"]:
        latest = quote(str(result["latest_version"]), safe="")
        return RedirectResponse(url=f"/settings?update=available&latest={latest}", status_code=303)
    return RedirectResponse(url="/settings?update=current", status_code=303)


@router.post("/install-update")
async def install_update(_=Depends(require_auth)):
    """Start only the documented, root-owned systemd update unit."""
    if start_self_update():
        return RedirectResponse(url="/settings?update=started", status_code=303)
    return RedirectResponse(url="/settings?update=install_error", status_code=303)


@router.post("/save")
async def save_settings(
    request: Request,
    conn=Depends(get_db),
    _=Depends(require_auth),
    logo_dev_token: str = Form(""),
):
    if logo_dev_token.strip():
        set_setting(conn, "logo_dev_token", logo_dev_token.strip())
        clear_missing_logo_cache(conn)
    return RedirectResponse(url="/settings?saved=1", status_code=303)


@router.post("/refresh-schedule")
async def save_refresh_schedule(
    refresh_time_1: str = Form(...),
    refresh_time_2: str = Form(...),
    conn=Depends(get_db),
    _=Depends(require_auth),
):
    try:
        save_refresh_times(conn, [refresh_time_1, refresh_time_2])
    except ValueError:
        return RedirectResponse(url="/settings?schedule_error=1", status_code=303)
    return RedirectResponse(url="/settings?saved=1", status_code=303)


@router.post("/clear-logo-key")
async def clear_logo_key(conn=Depends(get_db), _=Depends(require_auth)):
    conn.execute("DELETE FROM settings WHERE key='logo_dev_token'")
    return RedirectResponse(url="/settings?saved=1", status_code=303)


@router.post("/bitvavo")
async def save_bitvavo(
    api_key: str = Form(""),
    api_secret: str = Form(""),
    conn=Depends(get_db),
    _=Depends(require_auth),
):
    api_key, api_secret = api_key.strip(), api_secret.strip()
    if not api_key and not api_secret and has_bitvavo_credentials(conn):
        return RedirectResponse(url="/settings?saved=1", status_code=303)
    if not api_key or not api_secret:
        return RedirectResponse(url="/settings?bitvavo_error=missing", status_code=303)
    try:
        result = sync_bitvavo(conn, api_key, api_secret)
    except BitvavoError as exc:
        return RedirectResponse(url=f"/settings?bitvavo_error={quote(str(exc)[:180])}", status_code=303)
    save_bitvavo_credentials(conn, api_key, api_secret)
    return RedirectResponse(url=f"/settings?bitvavo_saved={result['balances']}", status_code=303)


@router.post("/clear-bitvavo")
async def clear_bitvavo(conn=Depends(get_db), _=Depends(require_auth)):
    clear_bitvavo_credentials(conn)
    return RedirectResponse(url="/settings?saved=1", status_code=303)


@router.post("/delete-transactions")
async def delete_transactions(conn=Depends(get_db), _=Depends(require_auth)):
    """Delete all transactions, prices and cash events. Keep accounts and instruments."""
    conn.execute("DELETE FROM transactions")
    conn.execute("DELETE FROM cash_events")
    conn.execute("DELETE FROM prices")
    conn.execute("DELETE FROM balance_snapshots")
    conn.execute("DELETE FROM import_log")
    conn.execute("DELETE FROM import_staging")
    conn.execute("DELETE FROM crypto_balances")
    conn.execute("DELETE FROM crypto_transactions")
    conn.execute("DELETE FROM crypto_prices")
    conn.execute("DELETE FROM crypto_portfolio_snapshots")
    conn.execute("DELETE FROM settings WHERE key IN ('bitvavo_last_sync','bitvavo_last_error')")
    conn.execute("UPDATE settings SET value='idle' WHERE key='ticker_map_status'")
    conn.commit()
    return RedirectResponse(url="/settings?deleted=transactions", status_code=303)


@router.post("/delete-all")
async def delete_all(conn=Depends(get_db), _=Depends(require_auth)):
    """Full reset: delete all data except WebAuthn credentials and settings."""
    conn.execute("DELETE FROM transactions")
    conn.execute("DELETE FROM cash_events")
    conn.execute("DELETE FROM prices")
    conn.execute("DELETE FROM balance_snapshots")
    conn.execute("DELETE FROM import_log")
    conn.execute("DELETE FROM import_staging")
    conn.execute("DELETE FROM crypto_balances")
    conn.execute("DELETE FROM crypto_transactions")
    conn.execute("DELETE FROM crypto_prices")
    conn.execute("DELETE FROM crypto_portfolio_snapshots")
    conn.execute("DELETE FROM settings WHERE key IN ('bitvavo_last_sync','bitvavo_last_error')")
    conn.execute("DELETE FROM instruments")
    conn.execute("DELETE FROM accounts")
    conn.execute("UPDATE settings SET value='idle' WHERE key='ticker_map_status'")
    conn.commit()
    return RedirectResponse(url="/settings?deleted=all", status_code=303)


@router.post("/reset-one-ticker/{instrument_id}")
async def reset_one_ticker(instrument_id: int, conn=Depends(get_db), _=Depends(require_auth)):
    """Clear the ticker symbol and cached prices for a single instrument.

    Prices are deleted so that when a new ticker is mapped, stale prices from
    the old ticker (possibly in a different currency/unit, e.g. GBX pence for
    ULVR.L vs EUR cents for UNA.AS) do not pollute the new ticker's data.
    Currency is also reset to NULL so it is re-fetched from yfinance.
    """
    import sys
    conn.execute("UPDATE instruments SET symbol = NULL, currency = NULL WHERE id=?", (instrument_id,))
    deleted = conn.execute("DELETE FROM prices WHERE instrument_id=?", (instrument_id,)).rowcount
    conn.commit()
    print(f"[ticker-reset] cleared ticker+{deleted} prices for instrument {instrument_id}", file=sys.stderr, flush=True)
    return RedirectResponse(url="/settings?saved=1", status_code=303)


@router.post("/reset-all-tickers")
async def reset_all_tickers(conn=Depends(get_db), _=Depends(require_auth)):
    """Clear all ticker symbols and cached prices so auto-map-tickers re-validates them.

    Prices are deleted so stale data (wrong currency/unit from old tickers) is
    fully removed before new tickers are mapped and new prices are fetched.
    """
    import sys
    result = conn.execute("UPDATE instruments SET symbol = NULL, currency = NULL WHERE symbol IS NOT NULL")
    deleted = conn.execute("DELETE FROM prices").rowcount
    conn.commit()
    print(f"[ticker-reset] cleared {result.rowcount} ticker(s) and {deleted} price row(s)", file=sys.stderr, flush=True)
    return RedirectResponse(url="/settings?saved=1", status_code=303)


@router.post("/refresh-classifications")
async def refresh_classifications(conn=Depends(get_db), _=Depends(require_auth)):
    """Re-fetch sector/region/asset_type + ETF/fund composition for all
    mapped instruments (top holdings, sector weightings, asset classes,
    equity metrics — shown on the instrument page, and used to split an
    ETF's value across multiple sectors in the allocation chart instead of
    one "Unclassified" blob).

    Sector/region/asset_type updates only fill in currently-empty fields
    (manual overrides are never touched); fund composition data is cached
    for a week before re-fetching, so this is always safe and cheap to
    re-run.
    """
    import sys
    import time
    from ..services import prices as svc_prices

    rows = conn.execute(
        "SELECT id, symbol FROM instruments WHERE symbol IS NOT NULL AND symbol != ''"
    ).fetchall()
    updated = 0
    for i, row in enumerate(rows):
        if i > 0:
            time.sleep(0.3)  # stay polite to Yahoo Finance
        try:
            if svc_prices.refresh_instrument_info(conn, row["id"], row["symbol"]):
                updated += 1
        except Exception as exc:
            print(f"[classify-refresh] {row['symbol']}: {exc}", file=sys.stderr, flush=True)
        try:
            svc_prices.refresh_fund_data(conn, row["id"], row["symbol"])
        except Exception as exc:
            print(f"[fund-data-refresh] {row['symbol']}: {exc}", file=sys.stderr, flush=True)
    return RedirectResponse(url=f"/settings?classified={updated}", status_code=303)


@router.get("/backup")
async def backup_db(conn=Depends(get_db), _=Depends(require_auth)):
    """Stream the SQLite database file as a download."""
    import io, tempfile, os, sqlite3
    from datetime import date

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        dest = sqlite3.connect(tmp_path)
        conn.backup(dest)
        dest.close()
        with open(tmp_path, "rb") as f:
            data = f.read()
    finally:
        os.unlink(tmp_path)

    filename = f"portfolio-backup-{date.today()}.db"
    return StreamingResponse(
        iter([data]),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store, private",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )
