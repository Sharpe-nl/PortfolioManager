"""Settings page."""
from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

from ..auth import list_credentials
from ..db import get_db, get_setting, set_setting
from ..helpers import templates, require_auth
from ..services.logo_cache import clear_missing_logo_cache
from ..services.refresh_scheduler import (
    DEFAULT_REFRESH_TIMEZONE,
    get_refresh_times,
    get_refresh_timezone,
    save_refresh_times,
    save_refresh_timezone,
)
from ..services.updates import check_for_update, current_version, self_update_enabled, start_self_update

router = APIRouter(prefix="/settings", tags=["settings"])
_MAX_RESTORE_BYTES = 100 * 1024 * 1024
_RESTORE_DATA_TABLES = (
    "accounts", "instruments", "transactions", "cash_events", "balance_snapshots",
    "savings_interest_rates", "savings_interest_adjustments", "crypto_balances", "crypto_transactions",
)


def _restore_allowed(conn) -> bool:
    return all(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0 for table in _RESTORE_DATA_TABLES)


def _validate_backup(path: str) -> None:
    source = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("invalid")
        tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"accounts", "transactions", "cash_events", "settings", "_migrations"}.issubset(tables):
            raise ValueError("invalid")
        expected = {path.name for path in (Path(__file__).parent.parent.parent / "migrations").glob("*.sql")}
        applied = {row[0] for row in source.execute("SELECT name FROM _migrations")}
        if not expected.issubset(applied):
            raise ValueError("outdated")
    finally:
        source.close()


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
        "refresh_time_1": refresh_times[0],
        "refresh_time_2": refresh_times[1] if len(refresh_times) > 1 else refresh_times[0],
        "refresh_last_run": get_setting(conn, "automatic_refresh_last_run"),
        "refresh_timezone": get_refresh_timezone(conn).key,
        "default_refresh_timezone": DEFAULT_REFRESH_TIMEZONE,
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
        "restore_allowed": _restore_allowed(conn),
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
    refresh_timezone: str = Form(DEFAULT_REFRESH_TIMEZONE),
    conn=Depends(get_db),
    _=Depends(require_auth),
):
    try:
        save_refresh_times(conn, [refresh_time_1, refresh_time_2])
        save_refresh_timezone(conn, refresh_timezone)
    except ValueError:
        return RedirectResponse(url="/settings?schedule_error=1", status_code=303)
    return RedirectResponse(url="/settings?saved=1", status_code=303)


@router.post("/clear-logo-key")
async def clear_logo_key(conn=Depends(get_db), _=Depends(require_auth)):
    conn.execute("DELETE FROM settings WHERE key='logo_dev_token'")
    return RedirectResponse(url="/settings?saved=1", status_code=303)


@router.post("/restore")
async def restore_db(
    backup: UploadFile = File(...),
    conn=Depends(get_db),
    _=Depends(require_auth),
):
    """Restore a verified same-version backup only into an empty installation."""
    if not _restore_allowed(conn):
        return RedirectResponse(url="/settings?restore=not_empty", status_code=303)
    suffix = Path(backup.filename or "backup.db").suffix or ".db"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        temp_path = handle.name
        size = 0
        while chunk := await backup.read(1024 * 1024):
            size += len(chunk)
            if size > _MAX_RESTORE_BYTES:
                handle.close()
                os.unlink(temp_path)
                return RedirectResponse(url="/settings?restore=too_large", status_code=303)
            handle.write(chunk)
    try:
        _validate_backup(temp_path)
        source = sqlite3.connect(temp_path)
        try:
            source.backup(conn)
        finally:
            source.close()
        conn.commit()
    except (ValueError, sqlite3.Error):
        return RedirectResponse(url="/settings?restore=invalid", status_code=303)
    finally:
        os.unlink(temp_path)
    return RedirectResponse(url="/settings?restore=success", status_code=303)


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
