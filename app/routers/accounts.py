"""Account management routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..db import get_db
from ..helpers import templates, require_auth
from ..services.portfolio import list_accounts

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("", response_class=HTMLResponse)
async def accounts_page(request: Request, conn=Depends(get_db), _=Depends(require_auth)):
    accounts = list_accounts(conn)
    account_data = []
    for acc in accounts:
        # Total value for this account
        val_row = conn.execute(
            """SELECT SUM(CAST(t.quantity AS REAL) * CAST(p.close AS REAL)) AS total
               FROM transactions t
               JOIN (
                   SELECT instrument_id, close FROM prices
                   GROUP BY instrument_id HAVING date = MAX(date)
               ) p ON p.instrument_id = t.instrument_id
               WHERE t.account_id = ?""",
            (acc.id,),
        ).fetchone()

        last_txn = conn.execute(
            "SELECT MAX(ts) AS last_ts FROM transactions WHERE account_id=?",
            (acc.id,),
        ).fetchone()

        snapshot = conn.execute(
            "SELECT balance_eur, date FROM balance_snapshots "
            "WHERE account_id=? ORDER BY date DESC LIMIT 1",
            (acc.id,),
        ).fetchone()

        account_data.append({
            "account": acc,
            "total_value": float(val_row["total"]) if val_row and val_row["total"] else 0.0,
            "last_transaction": last_txn["last_ts"] if last_txn else None,
            "latest_snapshot": dict(snapshot) if snapshot else None,
        })

    return templates.TemplateResponse("accounts.html", {
        "request": request,
        "account_data": account_data,
    })


@router.post("/add")
async def add_account(
    request: Request,
    conn=Depends(get_db),
    _=Depends(require_auth),
    name: str = Form(...),
    type: str = Form(...),
    currency: str = Form("EUR"),
):
    conn.execute(
        "INSERT INTO accounts(name, type, currency) VALUES (?,?,?)",
        (name.strip(), type, currency.upper().strip()),
    )
    return RedirectResponse(url="/accounts", status_code=303)


@router.get("/{account_id}/edit", response_class=HTMLResponse)
async def edit_account_page(
    request: Request,
    account_id: int,
    conn=Depends(get_db),
    _=Depends(require_auth),
):
    acc = conn.execute(
        "SELECT * FROM accounts WHERE id=?", (account_id,)
    ).fetchone()
    if not acc:
        return RedirectResponse(url="/accounts", status_code=303)
    return templates.TemplateResponse("accounts.html", {
        "request": request,
        "account_data": [],
        "editing": dict(acc),
    })


@router.post("/{account_id}/edit")
async def edit_account(
    request: Request,
    account_id: int,
    conn=Depends(get_db),
    _=Depends(require_auth),
    name: str = Form(...),
    type: str = Form(...),
    currency: str = Form("EUR"),
):
    conn.execute(
        "UPDATE accounts SET name=?, type=?, currency=? WHERE id=?",
        (name.strip(), type, currency.upper().strip(), account_id),
    )
    return RedirectResponse(url="/accounts", status_code=303)


@router.post("/{account_id}/delete")
async def delete_account(account_id: int, conn=Depends(get_db), _=Depends(require_auth)):
    """Delete an account and the data that cannot outlive it."""
    for table in ("transactions", "cash_events", "balance_snapshots", "import_log", "import_staging", "savings_interest_rates", "savings_interest_adjustments"):
        if table == "import_staging":
            continue  # staging rows have no account_id
        conn.execute(f"DELETE FROM {table} WHERE account_id=?", (account_id,))
    conn.execute("DELETE FROM accounts WHERE id=?", (account_id,))
    return RedirectResponse(url="/accounts", status_code=303)
