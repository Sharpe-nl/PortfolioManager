"""Savings-account interest calculations.

Interest is calculated from the most recent balance snapshot.  A new snapshot
therefore represents the bank's confirmed balance and becomes the new base.
"""
from __future__ import annotations

import calendar
import sqlite3
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

_CENT = Decimal("0.01")
_ZERO = Decimal("0")


def _d(value: object) -> Decimal:
    return Decimal(str(value or "0"))


def _next_date(value: date, frequency: str) -> date:
    if frequency == "weekly":
        return value + timedelta(days=7)
    if frequency == "yearly":
        return value.replace(year=value.year + 1)
    month = value.month + 1
    year = value.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    return value.replace(year=year, month=month, day=min(value.day, calendar.monthrange(year, month)[1]))


def account_interest(conn: sqlite3.Connection, account_id: int, as_of: date | None = None) -> dict:
    """Return confirmed balance plus scheduled, compounded interest to *as_of*.

    A rate applies from its start date until the next rate begins.  Manual
    adjustments are added on their date and take part in later compounding.
    """
    as_of = as_of or date.today()
    snapshot = conn.execute(
        "SELECT balance_eur, date FROM balance_snapshots WHERE account_id=? AND date<=? ORDER BY date DESC, id DESC LIMIT 1",
        (account_id, as_of.isoformat()),
    ).fetchone()
    if not snapshot:
        return {"balance": _ZERO, "principal": _ZERO, "interest": _ZERO, "events": [], "as_of": as_of.isoformat()}
    balance = _d(snapshot["balance_eur"]).quantize(_CENT)
    principal = balance
    start = date.fromisoformat(snapshot["date"])
    rates = conn.execute(
        "SELECT annual_rate, payout_frequency, starts_on FROM savings_interest_rates WHERE account_id=? AND starts_on<=? ORDER BY starts_on",
        (account_id, as_of.isoformat()),
    ).fetchall()
    adjustments = conn.execute(
        "SELECT id, date, amount_eur, description FROM savings_interest_adjustments WHERE account_id=? AND date>=? AND date<=? ORDER BY date, id",
        (account_id, start.isoformat(), as_of.isoformat()),
    ).fetchall()
    events = []
    cursor = start
    for index, rate in enumerate(rates):
        rate_start = max(date.fromisoformat(rate["starts_on"]), start)
        if rate_start > as_of:
            break
        next_rate = date.fromisoformat(rates[index + 1]["starts_on"]) if index + 1 < len(rates) else as_of + timedelta(days=1)
        period_end = min(next_rate - timedelta(days=1), as_of)
        if period_end < rate_start:
            continue
        payout = _next_date(rate_start, rate["payout_frequency"])
        while payout <= period_end:
            annual = _d(rate["annual_rate"]) / Decimal("100")
            divisor = {"weekly": Decimal("52"), "monthly": Decimal("12"), "yearly": Decimal("1")}[rate["payout_frequency"]]
            amount = (balance * annual / divisor).quantize(_CENT, ROUND_HALF_UP)
            balance += amount
            events.append({"date": payout.isoformat(), "amount": amount, "kind": "automatic"})
            payout = _next_date(payout, rate["payout_frequency"])
        cursor = max(cursor, period_end)
    for adjustment in adjustments:
        amount = _d(adjustment["amount_eur"]).quantize(_CENT)
        balance += amount
        events.append({"date": adjustment["date"], "amount": amount, "kind": "manual", "id": adjustment["id"], "description": adjustment["description"]})
    interest = (balance - principal).quantize(_CENT)
    active_rate = rates[-1] if rates else None
    next_payout = None
    if active_rate:
        payout = _next_date(date.fromisoformat(active_rate["starts_on"]), active_rate["payout_frequency"])
        while payout <= as_of:
            payout = _next_date(payout, active_rate["payout_frequency"])
        next_payout = payout.isoformat()
    return {
        "balance": balance.quantize(_CENT), "principal": principal, "interest": interest,
        "events": sorted(events, key=lambda e: e["date"], reverse=True), "as_of": as_of.isoformat(),
        "active_rate": dict(active_rate) if active_rate else None, "next_payout": next_payout,
    }


def savings_accounts(conn: sqlite3.Connection, include_hidden: bool = True) -> list[dict]:
    where = "WHERE a.type='savings'" + ("" if include_hidden else " AND a.include_in_dashboard=1")
    rows = conn.execute(f"SELECT a.* FROM accounts a {where} ORDER BY a.name").fetchall()
    result = []
    for row in rows:
        data = account_interest(conn, row["id"])
        result.append({**dict(row), **data})
    return result
