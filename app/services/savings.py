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


def _tiered_interest(balance: Decimal, rate: dict) -> Decimal:
    """Interest for one payout, including optional bonus-rate tiers."""
    divisor = {"weekly": Decimal("52"), "monthly": Decimal("12"), "yearly": Decimal("1")}[rate["payout_frequency"]]
    tiers = rate.get("tiers") or []
    if not tiers:
        return (balance * _d(rate["annual_rate"]) / Decimal("100") / divisor).quantize(_CENT, ROUND_HALF_UP)
    total = _ZERO
    # The base rate applies below the first tier. Each tier replaces it from
    # its threshold until the next tier's threshold.
    first_threshold = _d(tiers[0]["min_balance_eur"])
    total += min(balance, first_threshold) * _d(rate["annual_rate"]) / Decimal("100") / divisor
    for index, tier in enumerate(tiers):
        lower = _d(tier["min_balance_eur"])
        upper = _d(tiers[index + 1]["min_balance_eur"]) if index + 1 < len(tiers) else balance
        portion = max(_ZERO, min(balance, upper) - lower)
        total += portion * _d(tier["annual_rate"]) / Decimal("100") / divisor
    return total.quantize(_CENT, ROUND_HALF_UP)


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
    if snapshot:
        balance = _d(snapshot["balance_eur"]).quantize(_CENT)
        principal = balance
        start = date.fromisoformat(snapshot["date"])
    else:
        first = conn.execute(
            "SELECT MIN(day) AS day FROM ("
            "SELECT substr(ts,1,10) AS day FROM cash_events WHERE account_id=? AND type IN ('deposit','withdrawal') "
            "UNION ALL SELECT date AS day FROM savings_interest_adjustments WHERE account_id=? "
            "UNION ALL SELECT starts_on AS day FROM savings_interest_rates WHERE account_id=?"
            ")",
            (account_id, account_id, account_id),
        ).fetchone()["day"]
        if not first:
            return {"balance": _ZERO, "principal": _ZERO, "interest": _ZERO, "events": [], "as_of": as_of.isoformat(), "active_rate": None, "next_payout": None}
        balance = principal = _ZERO
        start = date.fromisoformat(first)
    rates = [dict(row) for row in conn.execute(
        "SELECT id, annual_rate, payout_frequency, starts_on, ends_on FROM savings_interest_rates WHERE account_id=? AND starts_on<=? ORDER BY starts_on",
        (account_id, as_of.isoformat()),
    ).fetchall()]
    for rate in rates:
        rate["tiers"] = [dict(row) for row in conn.execute(
            "SELECT min_balance_eur, annual_rate FROM savings_interest_rate_tiers WHERE rate_id=? ORDER BY CAST(min_balance_eur AS REAL)",
            (rate["id"],),
        ).fetchall()]
    adjustments = conn.execute(
        "SELECT id, date, amount_eur, description FROM savings_interest_adjustments WHERE account_id=? AND date>=? AND date<=? ORDER BY date, id",
        (account_id, start.isoformat(), as_of.isoformat()),
    ).fetchall()
    cash_movements = conn.execute(
        "SELECT id, ts, type, amount_eur, description FROM cash_events "
        "WHERE account_id=? AND type IN ('deposit','withdrawal') AND substr(ts,1,10)>=? AND substr(ts,1,10)<=? ORDER BY ts, id",
        (account_id, start.isoformat(), as_of.isoformat()),
    ).fetchall()
    events = []
    timeline = []
    for index, rate in enumerate(rates):
        rate_start = max(date.fromisoformat(rate["starts_on"]), start)
        if rate_start > as_of:
            break
        next_rate = date.fromisoformat(rates[index + 1]["starts_on"]) if index + 1 < len(rates) else as_of + timedelta(days=1)
        rate_end = date.fromisoformat(rate["ends_on"]) if rate["ends_on"] else as_of
        period_end = min(next_rate - timedelta(days=1), rate_end, as_of)
        if period_end < rate_start:
            continue
        payout = _next_date(rate_start, rate["payout_frequency"])
        while payout <= period_end:
            timeline.append((payout, 2, "automatic", rate))
            payout = _next_date(payout, rate["payout_frequency"])
    for adjustment in adjustments:
        timeline.append((date.fromisoformat(adjustment["date"]), 1, "manual", adjustment))
    for movement in cash_movements:
        timeline.append((date.fromisoformat(movement["ts"][:10]), 0, movement["type"], movement))
    for event_date, _priority, kind, source in sorted(timeline, key=lambda item: (item[0], item[1])):
        if kind == "automatic":
            amount = _tiered_interest(balance, source)
            balance += amount
            events.append({"date": event_date.isoformat(), "amount": amount, "kind": "automatic"})
        elif kind == "manual":
            amount = _d(source["amount_eur"]).quantize(_CENT)
            balance += amount
            events.append({"date": event_date.isoformat(), "amount": amount, "kind": "manual", "id": source["id"], "description": source["description"]})
        else:
            amount = _d(source["amount_eur"]).quantize(_CENT)
            balance += amount
            principal += amount
            events.append({"date": event_date.isoformat(), "amount": amount, "kind": kind, "id": source["id"], "description": source["description"]})
    interest = (balance - principal).quantize(_CENT)
    active_rate = next((rate for rate in reversed(rates) if not rate["ends_on"] or rate["ends_on"] >= as_of.isoformat()), None)
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
