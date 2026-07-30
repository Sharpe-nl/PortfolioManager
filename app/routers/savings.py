"""Savings-account management."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..db import get_db
from ..helpers import require_auth, templates
from ..services.savings import account_interest, savings_accounts

router = APIRouter(prefix="/savings", tags=["savings"])


def _savings_account(conn, account_id: int):
    return conn.execute("SELECT * FROM accounts WHERE id=? AND type='savings'", (account_id,)).fetchone()


def _signed_cash_amount(amount_eur: str, movement_type: str) -> str | None:
    if movement_type not in {"deposit", "withdrawal"}:
        return None
    try:
        amount = abs(Decimal(amount_eur))
    except (InvalidOperation, TypeError):
        return None
    if amount <= 0:
        return None
    return str(amount if movement_type == "deposit" else -amount)


def _settings_redirect(conn, account_id: int) -> RedirectResponse:
    """Commit before the redirected page reads through a new connection."""
    conn.commit()
    return RedirectResponse(url=f"/savings/{account_id}/settings?saved=1", status_code=303)


def _cash_movements(conn, account_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, substr(ts,1,10) AS date, type, amount_eur, description "
        "FROM cash_events WHERE account_id=? AND type IN ('deposit','withdrawal') "
        "ORDER BY ts DESC, id DESC",
        (account_id,),
    ).fetchall()
    return [
        {**dict(row), "amount_eur": str(abs(Decimal(row["amount_eur"])))}
        for row in rows
    ]


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
    for rate in context["rates"]:
        rate["tiers"] = [dict(row) for row in conn.execute("SELECT * FROM savings_interest_rate_tiers WHERE rate_id=? ORDER BY CAST(min_balance_eur AS REAL)", (rate["id"],))]
    context["cash_movements"] = _cash_movements(conn, account_id)
    context["adjustments"] = [dict(row) for row in conn.execute("SELECT * FROM savings_interest_adjustments WHERE account_id=? ORDER BY date DESC, id DESC", (account_id,))]
    return templates.TemplateResponse("savings_settings.html", {"request": request, "account": context})


@router.post("/{account_id}/rate")
async def add_rate(account_id: int, annual_rate: str = Form(...), payout_frequency: str = Form(...), starts_on: str = Form(...), ends_on: str = Form(""), conn=Depends(get_db), _=Depends(require_auth)):
    if _savings_account(conn, account_id):
        conn.execute("INSERT INTO savings_interest_rates(account_id,annual_rate,payout_frequency,starts_on,ends_on) VALUES(?,?,?,?,?) ON CONFLICT(account_id,starts_on) DO UPDATE SET annual_rate=excluded.annual_rate,payout_frequency=excluded.payout_frequency,ends_on=excluded.ends_on", (account_id, annual_rate, payout_frequency, starts_on, ends_on or None))
    return _settings_redirect(conn, account_id)


@router.post("/{account_id}/snapshot")
async def add_snapshot(account_id: int, date: str = Form(...), balance_eur: str = Form(...), conn=Depends(get_db), _=Depends(require_auth)):
    if _savings_account(conn, account_id):
        conn.execute("INSERT OR REPLACE INTO balance_snapshots(account_id,date,balance_eur) VALUES(?,?,?)", (account_id, date, balance_eur))
    return _settings_redirect(conn, account_id)


@router.post("/{account_id}/cash")
async def add_cash_movement(account_id: int, date: str = Form(...), movement_type: str = Form(...), amount_eur: str = Form(...), conn=Depends(get_db), _=Depends(require_auth)):
    signed_amount = _signed_cash_amount(amount_eur, movement_type)
    if _savings_account(conn, account_id) and signed_amount is not None:
        conn.execute(
            "INSERT INTO cash_events(account_id,ts,type,amount_eur,description) VALUES(?,?,?,?,?)",
            (account_id, f"{date}T00:00:00", movement_type, str(signed_amount), "Savings account movement"),
        )
    return _settings_redirect(conn, account_id)


@router.post("/{account_id}/interest")
async def add_interest(account_id: int, date: str = Form(...), amount_eur: str = Form(...), description: str = Form(""), conn=Depends(get_db), _=Depends(require_auth)):
    if _savings_account(conn, account_id):
        conn.execute("INSERT INTO savings_interest_adjustments(account_id,date,amount_eur,description) VALUES(?,?,?,?)", (account_id, date, amount_eur, description.strip() or None))
    return _settings_redirect(conn, account_id)


@router.post("/{account_id}/visibility")
async def set_visibility(account_id: int, include_in_dashboard: int = Form(0), conn=Depends(get_db), _=Depends(require_auth)):
    if _savings_account(conn, account_id):
        conn.execute("UPDATE accounts SET include_in_dashboard=? WHERE id=?", (1 if include_in_dashboard else 0, account_id))
    return _settings_redirect(conn, account_id)


@router.post("/{account_id}/snapshot/{snapshot_id}/delete")
async def delete_snapshot(account_id: int, snapshot_id: int, conn=Depends(get_db), _=Depends(require_auth)):
    conn.execute("DELETE FROM balance_snapshots WHERE id=? AND account_id=?", (snapshot_id, account_id))
    return _settings_redirect(conn, account_id)


@router.post("/{account_id}/cash/{movement_id}/delete")
async def delete_cash_movement(account_id: int, movement_id: int, conn=Depends(get_db), _=Depends(require_auth)):
    conn.execute(
        "DELETE FROM cash_events WHERE id=? AND account_id=? AND type IN ('deposit','withdrawal') "
        "AND EXISTS(SELECT 1 FROM accounts WHERE id=? AND type='savings')",
        (movement_id, account_id, account_id),
    )
    return _settings_redirect(conn, account_id)


@router.post("/{account_id}/interest/{adjustment_id}/delete")
async def delete_interest(account_id: int, adjustment_id: int, conn=Depends(get_db), _=Depends(require_auth)):
    conn.execute("DELETE FROM savings_interest_adjustments WHERE id=? AND account_id=?", (adjustment_id, account_id))
    return _settings_redirect(conn, account_id)


@router.post("/{account_id}/rate/{rate_id}/edit")
async def edit_rate(account_id: int, rate_id: int, annual_rate: str = Form(...), payout_frequency: str = Form(...), starts_on: str = Form(...), ends_on: str = Form(""), conn=Depends(get_db), _=Depends(require_auth)):
    conn.execute("UPDATE savings_interest_rates SET annual_rate=?, payout_frequency=?, starts_on=?, ends_on=? WHERE id=? AND account_id=?", (annual_rate, payout_frequency, starts_on, ends_on or None, rate_id, account_id))
    return _settings_redirect(conn, account_id)


@router.post("/{account_id}/snapshot/{snapshot_id}/edit")
async def edit_snapshot(account_id: int, snapshot_id: int, date: str = Form(...), balance_eur: str = Form(...), conn=Depends(get_db), _=Depends(require_auth)):
    conn.execute("UPDATE balance_snapshots SET date=?, balance_eur=? WHERE id=? AND account_id=?", (date, balance_eur, snapshot_id, account_id))
    return _settings_redirect(conn, account_id)


@router.post("/{account_id}/cash/{movement_id}/edit")
async def edit_cash_movement(account_id: int, movement_id: int, date: str = Form(...), movement_type: str = Form(...), amount_eur: str = Form(...), conn=Depends(get_db), _=Depends(require_auth)):
    signed_amount = _signed_cash_amount(amount_eur, movement_type)
    if _savings_account(conn, account_id) and signed_amount is not None:
        conn.execute(
            "UPDATE cash_events SET ts=? || substr(ts,11), type=?, amount_eur=? "
            "WHERE id=? AND account_id=? AND type IN ('deposit','withdrawal')",
            (date, movement_type, signed_amount, movement_id, account_id),
        )
    return _settings_redirect(conn, account_id)


@router.post("/{account_id}/interest/{adjustment_id}/edit")
async def edit_interest(account_id: int, adjustment_id: int, date: str = Form(...), amount_eur: str = Form(...), description: str = Form(""), conn=Depends(get_db), _=Depends(require_auth)):
    conn.execute("UPDATE savings_interest_adjustments SET date=?, amount_eur=?, description=? WHERE id=? AND account_id=?", (date, amount_eur, description.strip() or None, adjustment_id, account_id))
    return _settings_redirect(conn, account_id)


@router.post("/{account_id}/rate/{rate_id}/delete")
async def delete_rate(account_id: int, rate_id: int, conn=Depends(get_db), _=Depends(require_auth)):
    conn.execute("DELETE FROM savings_interest_rates WHERE id=? AND account_id=?", (rate_id, account_id))
    return _settings_redirect(conn, account_id)


@router.post("/{account_id}/rate/{rate_id}/tier")
async def add_rate_tier(account_id: int, rate_id: int, min_balance_eur: str = Form(...), annual_rate: str = Form(...), conn=Depends(get_db), _=Depends(require_auth)):
    rate = conn.execute("SELECT 1 FROM savings_interest_rates WHERE id=? AND account_id=?", (rate_id, account_id)).fetchone()
    if rate:
        conn.execute("INSERT INTO savings_interest_rate_tiers(rate_id,min_balance_eur,annual_rate) VALUES(?,?,?) ON CONFLICT(rate_id,min_balance_eur) DO UPDATE SET annual_rate=excluded.annual_rate", (rate_id, min_balance_eur, annual_rate))
    return _settings_redirect(conn, account_id)


@router.post("/{account_id}/rate/{rate_id}/tier/{tier_id}/delete")
async def delete_rate_tier(account_id: int, rate_id: int, tier_id: int, conn=Depends(get_db), _=Depends(require_auth)):
    conn.execute("DELETE FROM savings_interest_rate_tiers WHERE id=? AND rate_id=? AND EXISTS(SELECT 1 FROM savings_interest_rates WHERE id=? AND account_id=?)", (tier_id, rate_id, rate_id, account_id))
    return _settings_redirect(conn, account_id)
