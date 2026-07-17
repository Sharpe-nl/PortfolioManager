"""Import routes: upload → preview → confirm."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from ..db import get_db
from ..helpers import templates, require_auth
from ..importers import degiro_transactions, degiro_account, generic
from ..services.portfolio import list_accounts

router = APIRouter(prefix="/import", tags=["import"])

_STAGING_TTL_MINUTES = 60


# ---------------------------------------------------------------------------
# Import landing page
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse)
async def import_page(request: Request, conn=Depends(get_db), _=Depends(require_auth)):
    _cleanup_staging(conn)
    accounts = list_accounts(conn)
    import_history = conn.execute(
        """SELECT il.*, a.name AS account_name
           FROM import_log il LEFT JOIN accounts a ON a.id=il.account_id
           ORDER BY il.imported_at DESC LIMIT 30"""
    ).fetchall()

    needs_mapping = conn.execute(
        "SELECT * FROM instruments WHERE symbol IS NULL AND isin IS NOT NULL ORDER BY name"
    ).fetchall()

    unclassified = conn.execute(
        """SELECT ce.*, a.name AS account_name
           FROM cash_events ce JOIN accounts a ON a.id=ce.account_id
           WHERE ce.type='other' ORDER BY ce.ts DESC LIMIT 50"""
    ).fetchall()

    return templates.TemplateResponse("import.html", {
        "request": request,
        "accounts": accounts,
        "import_history": [dict(r) for r in import_history],
        "needs_mapping": [dict(r) for r in needs_mapping],
        "unclassified": [dict(r) for r in unclassified],
    })


# ---------------------------------------------------------------------------
# Upload → stage → preview
# ---------------------------------------------------------------------------

@router.post("/upload")
async def upload(
    request: Request,
    conn=Depends(get_db),
    _=Depends(require_auth),
    account_id: int = Form(...),
    file: UploadFile = File(...),
):
    raw_bytes = await file.read()
    try:
        content = raw_bytes.decode("utf-8-sig")  # handles BOM
    except UnicodeDecodeError:
        content = raw_bytes.decode("latin-1")

    filename = file.filename or "upload.csv"

    # Auto-detect file type
    if degiro_transactions.is_transactions_csv(content):
        file_type = "degiro_transactions"
        parse_result = degiro_transactions.parse(content)
        rows = _stage_transactions(parse_result, account_id, conn)
    elif degiro_account.is_account_csv(content):
        file_type = "degiro_account"
        parse_result = degiro_account.parse(content)
        rows = _stage_account_events(parse_result, account_id, conn)
    else:
        file_type = "generic"
        parse_result = generic.parse(content)
        rows = _stage_generic(parse_result, account_id, conn)

    session_key = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    for row_type, status, description, error_msg, row_json in rows:
        conn.execute(
            """INSERT INTO import_staging
               (session_key, row_type, row_json, status, error_msg, created_at)
               VALUES (?,?,?,?,?,?)""",
            (session_key, row_type, row_json, status, error_msg, now),
        )

    request.session["import_session"] = session_key
    request.session["import_filename"] = filename
    request.session["import_file_type"] = file_type
    request.session["import_account_id"] = account_id

    return RedirectResponse(url="/import/preview", status_code=303)


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------

@router.get("/preview", response_class=HTMLResponse)
async def preview(request: Request, conn=Depends(get_db), _=Depends(require_auth)):
    session_key = request.session.get("import_session")
    if not session_key:
        return RedirectResponse(url="/import", status_code=303)

    staged = conn.execute(
        "SELECT * FROM import_staging WHERE session_key=? ORDER BY id",
        (session_key,),
    ).fetchall()

    counts = {"new": 0, "duplicate": 0, "error": 0, "informational": 0}
    for r in staged:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    return templates.TemplateResponse("import_preview.html", {
        "request": request,
        "staged": [dict(r) for r in staged],
        "counts": counts,
        "filename": request.session.get("import_filename"),
        "file_type": request.session.get("import_file_type"),
    })


# ---------------------------------------------------------------------------
# Confirm
# ---------------------------------------------------------------------------

@router.post("/confirm")
async def confirm(request: Request, conn=Depends(get_db), _=Depends(require_auth)):
    import sys
    session_key = request.session.pop("import_session", None)
    filename = request.session.pop("import_filename", "")
    file_type = request.session.pop("import_file_type", "")
    account_id = request.session.pop("import_account_id", None)

    if not session_key:
        request.session["import_result"] = {
            "imported": 0, "skipped": 0, "errors": 1,
            "error_details": ["Sessie verlopen — upload het bestand opnieuw."],
            "filename": filename,
        }
        return RedirectResponse(url="/import?result=1", status_code=303)

    staged = conn.execute(
        "SELECT * FROM import_staging WHERE session_key=? AND status='new'",
        (session_key,),
    ).fetchall()

    imported = skipped = errors_count = 0
    errors: list[str] = []

    print(f"[confirm] session={session_key[:8]}… file_type={file_type} "
          f"staged_new={len(staged)}", file=sys.stderr, flush=True)

    for r in staged:
        try:
            data = json.loads(r["row_json"])
            if r["row_type"] == "transaction":
                cur = _commit_staged_transaction(conn, data)
                if cur.rowcount:
                    imported += 1
                else:
                    skipped += 1  # UNIQUE silently ignored (intra-CSV duplicate)
            elif r["row_type"] == "cash_event":
                cur = _commit_staged_cash_event(conn, data)
                if cur.rowcount:
                    imported += 1
                else:
                    skipped += 1
            elif r["row_type"] == "balance":
                _commit_staged_balance(conn, data)
                imported += 1
        except Exception as exc:
            errors_count += 1
            errors.append(f"{r['row_type']}: {exc}")
            print(f"[confirm] row error: {r['row_type']} → {exc}", file=sys.stderr, flush=True)

    print(f"[confirm] done: imported={imported} errors={errors_count}", file=sys.stderr, flush=True)

    # Add pre-staged duplicates (detected at upload time)
    dup_rows = conn.execute(
        "SELECT COUNT(*) AS n FROM import_staging WHERE session_key=? AND status='duplicate'",
        (session_key,),
    ).fetchone()
    skipped += dup_rows["n"] if dup_rows else 0

    conn.execute(
        """INSERT INTO import_log
           (account_id, filename, file_type, imported_at, rows_imported,
            rows_skipped, rows_error, errors)
           VALUES (?,?,?,datetime('now'),?,?,?,?)""",
        (account_id, filename, file_type, imported, skipped, errors_count,
         json.dumps(errors) if errors else None),
    )
    conn.execute("DELETE FROM import_staging WHERE session_key=?", (session_key,))
    conn.commit()

    request.session["import_result"] = {
        "imported": imported,
        "skipped": skipped,
        "errors": errors_count,
        "error_details": errors[:5],
        "file_type": file_type,
        "filename": filename,
    }
    return RedirectResponse(url="/import?result=1", status_code=303)


# ---------------------------------------------------------------------------
# Internal staging helpers
# ---------------------------------------------------------------------------

def _check_transaction_dup(conn, account_id, order_id, ts, quantity, price,
                           dedup_hash: str | None = None) -> bool:
    """Check whether a transaction already exists in the DB.

    Priority:
    1. dedup_hash  — SHA-256 of the full raw CSV row (includes Saldo column).
       This is the most reliable discriminator: two buys of the same stock at
       the same price in the same minute are NOT duplicates if the running
       balance differs, and their hashes will differ.
    2. order_id   — DeGiro order ID (present in Transactions.csv, not always
       in Account.csv).
    3. ts + quantity + price fallback — only used when neither hash nor
       order_id is available (e.g. manually entered transactions).
    """
    # 1. Hash-based dedup (most precise)
    if dedup_hash:
        row = conn.execute(
            "SELECT 1 FROM transactions WHERE dedup_hash=? LIMIT 1",
            (dedup_hash,),
        ).fetchone()
        if row:
            return True
        # Hash not in DB — definitely not a dup (skip the weaker checks)
        return False

    # 2. Order-ID dedup
    if order_id:
        row = conn.execute(
            "SELECT 1 FROM transactions WHERE account_id=? AND order_id=? LIMIT 1",
            (account_id, order_id),
        ).fetchone()
        if row:
            return True

    # 3. Fallback: ts + quantity + price (may produce false positives for
    #    simultaneous identical buys, but unavoidable without a hash or order_id)
    row = conn.execute(
        "SELECT 1 FROM transactions WHERE account_id=? AND ts=? AND quantity=? AND price=? LIMIT 1",
        (account_id, ts, str(quantity), str(price)),
    ).fetchone()
    return row is not None


def _check_event_dup(conn, dedup_hash: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM cash_events WHERE dedup_hash=? LIMIT 1", (dedup_hash,)
    ).fetchone()
    return row is not None


def _stage_transactions(parse_result, account_id: int, conn) -> list[tuple]:
    from ..importers.degiro_transactions import get_or_create_instrument
    staged = []
    seen_keys: set = set()  # dedup within this upload session
    for txn in parse_result.rows:
        # Within-session dedup: use order_id if available, else hash
        dedup_key = txn.dedup_hash if hasattr(txn, 'dedup_hash') and txn.dedup_hash else \
                    (account_id, txn.order_id or "", txn.ts, str(txn.quantity), str(txn.price))
        in_session = dedup_key in seen_keys
        seen_keys.add(dedup_key)
        is_dup = in_session or _check_transaction_dup(
            conn, account_id, txn.order_id, txn.ts, txn.quantity, txn.price,
            dedup_hash=getattr(txn, 'dedup_hash', None),
        )
        status = "duplicate" if is_dup else "new"
        instrument_id = get_or_create_instrument(conn, txn.isin, txn.product, txn.exchange)
        direction = "Koop" if txn.quantity > 0 else "Verkoop"
        desc = f"{txn.ts[:10]}  {txn.product}  {direction} {abs(txn.quantity)}x  @{txn.price} {txn.price_currency}"
        row_json = json.dumps({
            "_label": desc,
            "account_id": account_id,
            "instrument_id": instrument_id,
            "ts": txn.ts,
            "quantity": str(txn.quantity),
            "price": str(txn.price),
            "local_currency": txn.local_currency,
            "fx_rate": str(txn.fx_rate) if txn.fx_rate else None,
            "value_eur": str(txn.value_eur),
            "fees_eur": str(txn.fees_eur),
            "order_id": txn.order_id,
            "dedup_hash": getattr(txn, 'dedup_hash', None),
            "source": "degiro_csv",
        })
        staged.append(("transaction", status, desc, None, row_json))

    for err in parse_result.errors:
        staged.append(("transaction", "error", err, err, "{}"))
    return staged


def _stage_account_events(parse_result, account_id: int, conn) -> list[tuple]:
    from ..importers.degiro_account import _get_instrument_id
    from ..importers.degiro_transactions import get_or_create_instrument
    staged = []
    seen_txn_keys: set = set()  # dedup within this upload session

    # Stage buy/sell transactions from account CSV (Koop/Verkoop rows)
    for txn in parse_result.txn_rows:
        # Use dedup_hash (SHA-256 of full CSV row incl. Saldo) as primary dedup key.
        # This correctly handles two purchases of the same stock at the same price
        # within the same minute — they look identical on ts+qty+price but the
        # running balance (Saldo) differs, so their hashes differ.
        dedup_key = txn.dedup_hash  # always set for account CSV rows
        in_session = dedup_key in seen_txn_keys
        seen_txn_keys.add(dedup_key)
        is_dup = in_session or _check_transaction_dup(
            conn, account_id, txn.order_id, txn.ts, txn.quantity, txn.price,
            dedup_hash=txn.dedup_hash,
        )
        status = "duplicate" if is_dup else "new"
        instrument_id = get_or_create_instrument(conn, txn.isin, txn.product, txn.exchange)
        direction = "Koop" if txn.quantity > 0 else "Verkoop"
        desc = (f"{txn.ts[:10]}  {txn.product}  {direction} {abs(txn.quantity)}x"
                f"  @{txn.price} {txn.price_currency}")
        row_json = json.dumps({
            "_label": desc,
            "account_id": account_id,
            "instrument_id": instrument_id,
            "ts": txn.ts,
            "quantity": str(txn.quantity),
            "price": str(txn.price),
            "local_currency": txn.local_currency,
            "fx_rate": str(txn.fx_rate) if txn.fx_rate else None,
            "value_eur": str(txn.value_eur),
            "fees_eur": str(txn.fees_eur),
            "order_id": txn.order_id,
            "dedup_hash": txn.dedup_hash,
            "source": "degiro_account_csv",
        })
        staged.append(("transaction", status, desc, None, row_json))

    # Corporate actions (splits, mergers): determine direction automatically.
    # Rule: if the ISIN already has buy transactions (in this CSV or in the DB),
    # the adjustment CLOSES that position (negative qty = sell).
    # Otherwise it OPENS a new position (positive qty = buy).
    bought_isins: set[str] = set()
    for txn in parse_result.txn_rows:
        if txn.quantity > 0 and txn.isin:
            bought_isins.add(txn.isin)
    for r in conn.execute(
        """SELECT DISTINCT i.isin FROM transactions t
           JOIN instruments i ON i.id=t.instrument_id
           WHERE t.account_id=? AND t.quantity > 0 AND i.isin IS NOT NULL""",
        (account_id,),
    ).fetchall():
        if r["isin"]:
            bought_isins.add(r["isin"])

    for ca in parse_result.corporate_actions:
        instrument_id = get_or_create_instrument(conn, ca.isin, ca.product, "")

        has_position = bool(ca.isin and ca.isin in bought_isins)
        if has_position:
            quantity  = -ca.quantity                  # close: sell
            value_eur =  ca.quantity * ca.price       # positive (value returned)
            direction_label = "Sluiten"
        else:
            quantity  =  ca.quantity                  # open: buy
            value_eur = -(ca.quantity * ca.price)     # negative (value received)
            direction_label = "Ontvangen"

        dedup_key = ca.dedup_hash
        in_session = dedup_key in seen_txn_keys
        seen_txn_keys.add(dedup_key)
        is_dup = in_session or _check_transaction_dup(
            conn, account_id, None, ca.ts, quantity, ca.price,
            dedup_hash=ca.dedup_hash,
        )
        status = "duplicate" if is_dup else "new"

        desc = (f"📋 {ca.ts[:10]}  {ca.product}  "
                f"Corp.action {direction_label} {abs(quantity)}x @ {ca.price} {ca.price_currency}")
        row_json = json.dumps({
            "_label": desc,
            "account_id": account_id,
            "instrument_id": instrument_id,
            "ts": ca.ts,
            "quantity": str(quantity),
            "price": str(ca.price),
            "local_currency": ca.price_currency,
            "fx_rate": None,
            "value_eur": str(value_eur),
            "fees_eur": "0",
            "order_id": None,
            "dedup_hash": ca.dedup_hash,
            "source": "corporate_action",
        })
        staged.append(("transaction", status, desc, None, row_json))

    # Stage cash events (dividend, deposit, fee, etc.)
    seen_event_hashes: set = set()
    for row in parse_result.rows:
        in_session = row.dedup_hash in seen_event_hashes
        seen_event_hashes.add(row.dedup_hash)
        is_dup = in_session or _check_event_dup(conn, row.dedup_hash)
        status = "duplicate" if is_dup else "new"
        instrument_id = _get_instrument_id(conn, row.isin, row.product)
        desc = f"{row.ts[:10]}  {row.description}  {row.amount_eur} EUR"
        row_json = json.dumps({
            "_label": desc,
            "account_id": account_id,
            "instrument_id": instrument_id,
            "ts": row.ts,
            "type": row.event_type,
            "amount_eur": str(row.amount_eur),
            "description": row.description,
            "dedup_hash": row.dedup_hash,
        })
        staged.append(("cash_event", status, desc, None, row_json))

    for err in parse_result.errors:
        staged.append(("cash_event", "error", err, err, "{}"))

    # Uninvested cash balance (from the running "Saldo" column) — stored as a
    # balance_snapshots row, same mechanism used for manual/generic accounts.
    cash_eur = _compute_cash_balance_eur(parse_result)
    if cash_eur is not None:
        desc = f"Cash saldo {parse_result.cash_balance_date}: {cash_eur} EUR"
        row_json = json.dumps({
            "account_id": account_id,
            "date": parse_result.cash_balance_date,
            "amount_eur": str(cash_eur),
        })
        staged.append(("balance", "new", desc, None, row_json))

    return staged


def _compute_cash_balance_eur(parse_result):
    """Convert the parser's per-currency cash balances to EUR.

    Prefers today's live FX rate (accurate "what is this worth right now"),
    falling back to the historical in-file rate (network-free, less accurate
    for currency that's been sitting uninvested since it was converted) only
    if a live rate can't be fetched (offline, or unsupported currency).
    """
    if not parse_result.cash_balances_raw:
        return None
    from decimal import Decimal, ROUND_HALF_UP
    from ..services.prices import to_eur_live

    total = Decimal("0")
    for ccy, amount in parse_result.cash_balances_raw.items():
        if amount == 0:
            continue  # fully swept back to zero — no FX rate needed
        live = to_eur_live(amount, ccy)
        if live is None:
            # At least one currency couldn't be converted live — fall back
            # to the parser's historical-rate estimate for the whole total
            # rather than mixing live and stale conversions.
            return parse_result.cash_balance_eur
        total += live
    return total.quantize(Decimal("0.01"), ROUND_HALF_UP)


def _stage_generic(parse_result, account_id: int, conn) -> list[tuple]:
    staged = []
    for row in parse_result.rows:
        if row.row_type == "transaction":
            is_dup = _check_transaction_dup(
                conn, account_id, None, f"{row.date}T00:00:00",
                row.quantity or 0, row.price or 0
            )
        elif row.row_type == "balance":
            is_dup = False
        else:
            is_dup = _check_event_dup(conn, row.dedup_hash)

        status = "duplicate" if is_dup else "new"
        from ..importers.generic import _get_or_create_instrument
        instrument_id = _get_or_create_instrument(conn, row.isin_or_name)
        row_json = json.dumps({
            "account_id": account_id,
            "instrument_id": instrument_id,
            "date": row.date,
            "row_type": row.row_type,
            "quantity": str(row.quantity) if row.quantity else None,
            "price": str(row.price) if row.price else None,
            "amount_eur": str(row.amount_eur),
            "description": row.description,
            "dedup_hash": row.dedup_hash,
        })
        desc = f"{row.date}  {row.row_type}  {row.isin_or_name}  {row.amount_eur} EUR"
        staged.append((row.row_type, status, desc, None, row_json))

    for err in parse_result.errors:
        staged.append(("error", "error", err, err, "{}"))
    return staged


def _commit_staged_transaction(conn, data: dict):
    return conn.execute(
        """INSERT OR IGNORE INTO transactions
           (account_id, instrument_id, ts, quantity, price, local_currency,
            fx_rate, value_eur, fees_eur, order_id, source, dedup_hash)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            data["account_id"], data["instrument_id"], data["ts"],
            data["quantity"], data["price"], data["local_currency"],
            data.get("fx_rate"), data["value_eur"], data.get("fees_eur", "0"),
            data.get("order_id"), data.get("source", "degiro_csv"),
            data.get("dedup_hash"),
        ),
    )


def _commit_staged_cash_event(conn, data: dict):
    return conn.execute(
        """INSERT OR IGNORE INTO cash_events
           (account_id, instrument_id, ts, type, amount_eur, description, dedup_hash)
           VALUES (?,?,?,?,?,?,?)""",
        (
            data["account_id"], data.get("instrument_id"), data["ts"],
            data["type"], data["amount_eur"], data.get("description"),
            data.get("dedup_hash"),
        ),
    )


def _commit_staged_balance(conn, data: dict) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO balance_snapshots(account_id, date, balance_eur)
           VALUES (?,?,?)""",
        (data["account_id"], data["date"], data["amount_eur"]),
    )


def _cleanup_staging(conn) -> None:
    """Delete staging rows older than TTL."""
    conn.execute(
        "DELETE FROM import_staging WHERE created_at < datetime('now', ?)",
        (f"-{_STAGING_TTL_MINUTES} minutes",),
    )
