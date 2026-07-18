"""Savings-account management."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..db import get_db
from ..helpers import require_auth, templates
from ..services.savings import account_interest, savings_accounts

router = APIRouter(prefix="/savings", tags=["savings"])


def _savings_account(conn, account_id: int):
    return conn.execute("SELECT * FROM accounts WHERE id=? AND type='savings'", (account_id,)).fetchone()


@router.get("", response_class=HTMLResponse)
async def savings_page(request: Request, conn=Depends(get_db), _=Depends(require_auth)):
    accounts = savings_accounts(conn)
    return templates.TemplateResponse("savings.html", {"request": request, "savings_accounts": accounts})


@router.get("/{account_id}/settings", response_class=HTMLResponse)
async def savings_settings(account_id: int, request: Request, conn=Depends(get_db), _=Depends(require_auth)):
    account = _savings_account(conn, account_id)
    if not account:
        return RedirectResponse(url="/savings", status_code=303)
    context = dict(account)
    context.update(account_interest(conn, account_id))
    context["rates"] = [dict(row) for row in conn.execute("SELECT * FROM savings_interest_rates WHERE account_id=? ORDER BY starts_on DESC", (account_id,))]
    context["snapshots"] = [dict(row) for row in conn.execute("SELECT * FROM balance_snapshots WHERE account_id=? ORDER BY date DESC, id DESC", (account_id,))]
    context["adjustments"] = [dict(row) for row in conn.execute("SELECT * FROM savings_interest_adjustments WHERE account_id=? ORDER BY date DESC, id DESC", (account_id,))]
    return templates.TemplateResponse("savings_settings.html", {"request": request, "account": context})


@router.post("/{account_id}/rate")
async def add_rate(account_id: int, annual_rate: str = Form(...), payout_frequency: str = Form(...), starts_on: str = Form(...), conn=Depends(get_db), _=Depends(require_auth)):
    if _savings_account(conn, account_id):
        conn.execute("INSERT INTO savings_interest_rates(account_id,annual_rate,payout_frequency,starts_on) VALUES(?,?,?,?) ON CONFLICT(account_id,starts_on) DO UPDATE SET annual_rate=excluded.annual_rate,payout_frequency=excluded.payout_frequency", (account_id, annual_rate, payout_frequency, starts_on))
    return RedirectResponse(url=f"/savings/{account_id}/settings?saved=1", status_code=303)


@router.post("/{account_id}/snapshot")
async def add_snapshot(account_id: int, date: str = Form(...), balance_eur: str = Form(...), conn=Depends(get_db), _=Depends(require_auth)):
    if _savings_account(conn, account_id):
        conn.execute("INSERT OR REPLACE INTO balance_snapshots(account_id,date,balance_eur) VALUES(?,?,?)", (account_id, date, balance_eur))
    return RedirectResponse(url=f"/savings/{account_id}/settings?saved=1", status_code=303)


@router.post("/{account_id}/cash")
async def add_cash_movement(account_id: int, date: str = Form(...), movement_type: str = Form(...), amount_eur: str = Form(...), conn=Depends(get_db), _=Depends(require_auth)):
    if _savings_account(conn, account_id) and movement_type in {"deposit", "withdrawal"}:
        amount = abs(float(amount_eur))
        signed_amount = amount if movement_type == "deposit" else -amount
        conn.execute(
            "INSERT INTO cash_events(account_id,ts,type,amount_eur,description) VALUES(?,?,?,?,?)",
            (account_id, f"{date}T00:00:00", movement_type, str(signed_amount), "Savings account movement"),
        )
    return RedirectResponse(url=f"/savings/{account_id}/settings?saved=1", status_code=303)


@router.post("/{account_id}/interest")
async def add_interest(account_id: int, date: str = Form(...), amount_eur: str = Form(...), description: str = Form(""), conn=Depends(get_db), _=Depends(require_auth)):
    if _savings_account(conn, account_id):
        conn.execute("INSERT INTO savings_interest_adjustments(account_id,date,amount_eur,description) VALUES(?,?,?,?)", (account_id, date, amount_eur, description.strip() or None))
    return RedirectResponse(url=f"/savings/{account_id}/settings?saved=1", status_code=303)


@router.post("/{account_id}/visibility")
async def set_visibility(account_id: int, include_in_dashboard: int = Form(0), conn=Depends(get_db), _=Depends(require_auth)):
    if _savings_account(conn, account_id):
        conn.execute("UPDATE accounts SET include_in_dashboard=? WHERE id=?", (1 if include_in_dashboard else 0, account_id))
    return RedirectResponse(url=f"/savings/{account_id}/settings?saved=1", status_code=303)


@router.post("/{account_id}/snapshot/{snapshot_id}/delete")
async def delete_snapshot(account_id: int, snapshot_id: int, conn=Depends(get_db), _=Depends(require_auth)):
    conn.execute("DELETE FROM balance_snapshots WHERE id=? AND account_id=?", (snapshot_id, account_id))
    return RedirectResponse(url=f"/savings/{account_id}/settings?saved=1", status_code=303)


@router.post("/{account_id}/interest/{adjustment_id}/delete")
async def delete_interest(account_id: int, adjustment_id: int, conn=Depends(get_db), _=Depends(require_auth)):
    conn.execute("DELETE FROM savings_interest_adjustments WHERE id=? AND account_id=?", (adjustment_id, account_id))
    return RedirectResponse(url=f"/savings/{account_id}/settings?saved=1", status_code=303)


@router.post("/{account_id}/rate/{rate_id}/edit")
async def edit_rate(account_id: int, rate_id: int, annual_rate: str = Form(...), payout_frequency: str = Form(...), starts_on: str = Form(...), conn=Depends(get_db), _=Depends(require_auth)):
    conn.execute("UPDATE savings_interest_rates SET annual_rate=?, payout_frequency=?, starts_on=? WHERE id=? AND account_id=?", (annual_rate, payout_frequency, starts_on, rate_id, account_id))
    return RedirectResponse(url=f"/savings/{account_id}/settings?saved=1", status_code=303)


@router.post("/{account_id}/snapshot/{snapshot_id}/edit")
async def edit_snapshot(account_id: int, snapshot_id: int, date: str = Form(...), balance_eur: str = Form(...), conn=Depends(get_db), _=Depends(require_auth)):
    conn.execute("UPDATE balance_snapshots SET date=?, balance_eur=? WHERE id=? AND account_id=?", (date, balance_eur, snapshot_id, account_id))
    return RedirectResponse(url=f"/savings/{account_id}/settings?saved=1", status_code=303)


@router.post("/{account_id}/interest/{adjustment_id}/edit")
async def edit_interest(account_id: int, adjustment_id: int, date: str = Form(...), amount_eur: str = Form(...), description: str = Form(""), conn=Depends(get_db), _=Depends(require_auth)):
    conn.execute("UPDATE savings_interest_adjustments SET date=?, amount_eur=?, description=? WHERE id=? AND account_id=?", (date, amount_eur, description.strip() or None, adjustment_id, account_id))
    return RedirectResponse(url=f"/savings/{account_id}/settings?saved=1", status_code=303)


@router.post("/{account_id}/rate/{rate_id}/delete")
async def delete_rate(account_id: int, rate_id: int, conn=Depends(get_db), _=Depends(require_auth)):
    conn.execute("DELETE FROM savings_interest_rates WHERE id=? AND account_id=?", (rate_id, account_id))
    return RedirectResponse(url=f"/savings/{account_id}/settings?saved=1", status_code=303)
