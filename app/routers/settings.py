"""Settings page."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

from ..auth import list_credentials
from ..db import get_db, get_setting, set_setting
from ..helpers import templates, require_auth

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_class=HTMLResponse)
async def settings_page(request: Request, conn=Depends(get_db), _=Depends(require_auth)):
    logo_dev_token_configured = bool(get_setting(conn, "logo_dev_token"))

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
        "webauthn_credentials": list_credentials(conn),
        "unmapped_instruments": [dict(r) for r in unmapped],
        "mapped_instruments": [dict(r) for r in mapped],
        "db_counts": {
            "transactions": txn_count,
            "instruments": inst_count,
            "accounts": acct_count,
        },
    })


@router.post("/save")
async def save_settings(
    request: Request,
    conn=Depends(get_db),
    _=Depends(require_auth),
    logo_dev_token: str = Form(""),
):
    if logo_dev_token.strip():
        set_setting(conn, "logo_dev_token", logo_dev_token.strip())
    return RedirectResponse(url="/settings?saved=1", status_code=303)


@router.post("/clear-logo-key")
async def clear_logo_key(conn=Depends(get_db), _=Depends(require_auth)):
    conn.execute("DELETE FROM settings WHERE key='logo_dev_token'")
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
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
