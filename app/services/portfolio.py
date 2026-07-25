"""Portfolio calculations: holdings, cost basis, P/L, allocation.

All arithmetic uses decimal.Decimal.  Money is NEVER stored as float.
Holdings are derived from transactions on each call — never stored.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date as _date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from ..models import Account, Holding, Instrument


_ZERO = Decimal("0")
_TWO = Decimal("0.01")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _d(s: str | None, default: str = "0") -> Decimal:
    if s is None:
        return Decimal(default)
    try:
        value = Decimal(s)
    except Exception:
        return Decimal(default)
    return value if value.is_finite() else Decimal(default)


def _row_to_instrument(row: sqlite3.Row) -> Instrument:
    return Instrument(
        id=row["id"],
        name=row["name"],
        isin=row["isin"],
        symbol=row["symbol"],
        exchange=row["exchange"],
        currency=row["currency"],
        trading_currency=row["trading_currency"],
        asset_type=row["asset_type"] or "other",
        sector=row["sector"],
        region=row["region"],
    )


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def list_accounts(conn: sqlite3.Connection) -> list[Account]:
    rows = conn.execute(
        "SELECT id, name, type, currency FROM accounts ORDER BY name"
    ).fetchall()
    return [Account(id=r["id"], name=r["name"], type=r["type"], currency=r["currency"])
            for r in rows]


def get_account(conn: sqlite3.Connection, account_id: int) -> Optional[Account]:
    row = conn.execute(
        "SELECT id, name, type, currency FROM accounts WHERE id=?", (account_id,)
    ).fetchone()
    if not row:
        return None
    return Account(id=row["id"], name=row["name"], type=row["type"], currency=row["currency"])


# ---------------------------------------------------------------------------
# Holdings
# ---------------------------------------------------------------------------

def _position_accounting(
    conn: sqlite3.Connection,
    account_id: int | None = None,
    through_ts: str | None = None,
) -> tuple[dict[tuple[int, int], dict], list[dict]]:
    """Calculate moving-average cost and realized P/L in chronological order.

    Cost must be reduced when shares are sold.  Averaging every buy ever made
    gives incorrect results after a position was completely sold and opened
    again, which was especially visible when the same ISIN was traded on more
    than one listing.
    """
    rows = conn.execute(
        """SELECT id, account_id, instrument_id, ts, quantity, value_eur, fees_eur
           FROM transactions
           WHERE (:acct IS NULL OR account_id = :acct)
             AND (:through_ts IS NULL OR ts <= :through_ts)
           ORDER BY account_id, instrument_id, ts, id""",
        {"acct": account_id, "through_ts": through_ts},
    ).fetchall()
    states: dict[tuple[int, int], dict] = {}
    sale_events: list[dict] = []
    for row in rows:
        key = (row["account_id"], row["instrument_id"])
        state = states.setdefault(key, {"quantity": _ZERO, "cost": _ZERO, "realized": _ZERO})
        quantity = _d(row["quantity"])
        value = _d(row["value_eur"])
        fees = _d(row["fees_eur"])
        if quantity > _ZERO:
            state["quantity"] += quantity
            state["cost"] += -(value + fees)
            continue
        if quantity >= _ZERO:
            continue

        sell_qty = -quantity
        held_qty = state["quantity"]
        matched_qty = min(sell_qty, max(held_qty, _ZERO))
        average_cost = state["cost"] / held_qty if held_qty > _ZERO else _ZERO
        cost_of_sold = average_cost * matched_qty
        proceeds = value + fees
        realized = proceeds - cost_of_sold
        state["quantity"] -= sell_qty
        state["cost"] -= cost_of_sold
        if abs(state["quantity"]) < Decimal("0.000001"):
            state["quantity"] = _ZERO
            state["cost"] = _ZERO
        state["realized"] += realized
        sale_events.append({
            "transaction_id": row["id"],
            "account_id": row["account_id"],
            "instrument_id": row["instrument_id"],
            "quantity": sell_qty,
            "proceeds": proceeds,
            "realized_pl": realized,
        })
    return states, sale_events

def get_holdings(
    conn: sqlite3.Connection,
    account_id: int | None = None,
) -> list[Holding]:
    """Return current holdings derived from transactions.

    Uses average cost method for cost basis.
    """
    sql = """
        SELECT
            t.account_id,
            a.name AS account_name,
            t.instrument_id,
            SUM(CAST(t.quantity AS REAL)) AS total_qty
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        WHERE (:acct IS NULL OR t.account_id = :acct)
        GROUP BY t.account_id, t.instrument_id
        HAVING ABS(SUM(CAST(t.quantity AS REAL))) > 0.000001
        ORDER BY a.name, t.instrument_id
    """
    rows = conn.execute(sql, {"acct": account_id}).fetchall()

    states, _ = _position_accounting(conn, account_id)
    instrument_ids = list({r["instrument_id"] for r in rows})
    instruments: dict[int, Instrument] = {}
    for iid in instrument_ids:
        irow = conn.execute(
            "SELECT id,isin,name,symbol,exchange,currency,trading_currency,asset_type,sector,region "
            "FROM instruments WHERE id=?",
            (iid,),
        ).fetchone()
        if irow:
            instruments[iid] = _row_to_instrument(irow)

    holdings: list[Holding] = []
    for r in rows:
        total_qty = Decimal(str(r["total_qty"]))
        state = states.get((r["account_id"], r["instrument_id"]), {})
        total_cost = state.get("cost", _ZERO)
        avg_cost = (total_cost / total_qty).quantize(_TWO, ROUND_HALF_UP) \
            if total_qty else _ZERO

        inst = instruments.get(r["instrument_id"])
        if not inst:
            continue

        # Current price from cache
        price_row = conn.execute(
            "SELECT close, currency FROM prices "
            "WHERE instrument_id=? ORDER BY date DESC LIMIT 1",
            (r["instrument_id"],),
        ).fetchone()

        current_price: Optional[Decimal] = None
        current_value: Optional[Decimal] = None
        unrealized_pl: Optional[Decimal] = None
        unrealized_pl_pct: Optional[Decimal] = None

        if price_row:
            current_price = _d(price_row["close"])
            current_value = (total_qty * current_price).quantize(_TWO, ROUND_HALF_UP)
            cost_basis = (total_qty * avg_cost).quantize(_TWO, ROUND_HALF_UP)
            unrealized_pl = (current_value - cost_basis).quantize(_TWO, ROUND_HALF_UP)
            if cost_basis:
                unrealized_pl_pct = (unrealized_pl / cost_basis * 100).quantize(_TWO, ROUND_HALF_UP)

        holdings.append(Holding(
            instrument=inst,
            account_id=r["account_id"],
            account_name=r["account_name"],
            quantity=total_qty,
            avg_cost=avg_cost,
            cost_basis=(total_qty * avg_cost).quantize(_TWO, ROUND_HALF_UP),
            current_price=current_price,
            current_value=current_value,
            unrealized_pl=unrealized_pl,
            unrealized_pl_pct=unrealized_pl_pct,
        ))

    # Calculate portfolio weights
    total_value = sum(
        h.current_value for h in holdings if h.current_value is not None
    ) or _ZERO
    for h in holdings:
        if h.current_value is not None and total_value:
            h.weight = (h.current_value / total_value * 100).quantize(_TWO, ROUND_HALF_UP)

    return holdings


# ---------------------------------------------------------------------------
# Realized P/L
# ---------------------------------------------------------------------------

def get_realized_pl(conn: sqlite3.Connection, account_id: int | None = None) -> Decimal:
    """Return realized P/L using the moving average at every sale."""
    _, events = _position_accounting(conn, account_id)
    return sum((event["realized_pl"] for event in events), _ZERO).quantize(_TWO, ROUND_HALF_UP)


def get_realized_pl_events(
    conn: sqlite3.Connection,
    account_id: int | None = None,
) -> list[dict]:
    """Per-sale realized P/L events using the cost at the moment of sale."""
    _, accounting_events = _position_accounting(conn, account_id)
    rows = conn.execute(
        """SELECT t.id, t.ts, i.name AS instrument_name, i.isin, i.symbol,
                  a.name AS account_name
           FROM transactions t
           JOIN instruments i ON i.id=t.instrument_id
           JOIN accounts a ON a.id=t.account_id
           WHERE CAST(t.quantity AS REAL) < 0
             AND (:acct IS NULL OR t.account_id=:acct)""",
        {"acct": account_id},
    ).fetchall()
    details = {row["id"]: row for row in rows}
    events = []
    for event in accounting_events:
        row = details[event["transaction_id"]]
        events.append({
            "ts": row["ts"],
            "instrument_id": event["instrument_id"],
            "instrument_name": row["instrument_name"],
            "isin": row["isin"],
            "symbol": row["symbol"],
            "account_name": row["account_name"],
            "quantity": event["quantity"],
            "proceeds": event["proceeds"].quantize(_TWO, ROUND_HALF_UP),
            "realized_pl": event["realized_pl"].quantize(_TWO, ROUND_HALF_UP),
        })
    return events


# ---------------------------------------------------------------------------
# Cash balance
# ---------------------------------------------------------------------------

def get_cash_balances(
    conn: sqlite3.Connection,
    account_id: int | None = None,
    include_savings: bool = True,
) -> list[dict]:
    """Return each account's latest current uninvested cash balance (EUR).

    Populated from balance_snapshots — written on every DeGiro Account.csv
    import (from the running "Saldo" column). When a later incremental import
    contains new activity, its cash effects are applied to the last snapshot.
    This keeps a balance current without counting sale proceeds twice beside a
    later purchase.
    """
    sql = """
        SELECT a.id AS account_id, a.name AS account_name,
               latest.balance_eur AS balance_eur, latest.date AS date
        FROM (
            SELECT account_id, balance_eur, date,
                   ROW_NUMBER() OVER (PARTITION BY account_id ORDER BY date DESC) AS rn
            FROM balance_snapshots
            WHERE (:acct IS NULL OR account_id = :acct)
        ) latest
        JOIN accounts a ON a.id = latest.account_id
        WHERE latest.rn = 1
          AND (a.type != 'savings' OR :include_savings = 1)
        ORDER BY a.name
    """
    rows = conn.execute(sql, {"acct": account_id, "include_savings": int(include_savings)}).fetchall()
    balances = []
    for r in rows:
        balance = _cash_balance_from_snapshot(
            conn, r["account_id"], r["date"], Decimal(str(r["balance_eur"]))
        )
        balances.append({
            "account_id": r["account_id"],
            "account_name": r["account_name"],
            "balance_eur": balance.quantize(_TWO, ROUND_HALF_UP),
            "date": r["date"],
        })
    return balances


def _cash_balance_from_snapshot(
    conn: sqlite3.Connection,
    account_id: int,
    snapshot_date: str,
    snapshot_balance: Decimal,
    through_date: str | None = None,
) -> Decimal:
    """Apply ledger activity after an end-of-day cash snapshot.

    DeGiro reports the trade amount and its commission as separate ledger
    entries. Therefore transaction ``value_eur`` is applied here while fees
    are supplied by their corresponding cash event, avoiding a double count.
    """
    end_ts = f"{through_date or '9999-12-31'}T23:59:59"
    transaction_delta = conn.execute(
        """SELECT COALESCE(SUM(CAST(value_eur AS REAL)), 0) AS total
           FROM transactions
           WHERE account_id=? AND ts > ? AND ts <= ?""",
        (account_id, f"{snapshot_date}T23:59:59", end_ts),
    ).fetchone()
    event_delta = conn.execute(
        """SELECT COALESCE(SUM(CAST(amount_eur AS REAL)), 0) AS total
           FROM cash_events
           WHERE account_id=? AND ts > ? AND ts <= ?""",
        (account_id, f"{snapshot_date}T23:59:59", end_ts),
    ).fetchone()
    return (
        snapshot_balance
        + Decimal(str(transaction_delta["total"] or 0))
        + Decimal(str(event_delta["total"] or 0))
    )


def get_cash_balance(
    conn: sqlite3.Connection,
    account_id: int | None = None,
) -> Decimal:
    """Return uninvested cash (EUR), summed across accounts' latest known balance."""
    return sum((b["balance_eur"] for b in get_cash_balances(conn, account_id, include_savings=False)), _ZERO)


# ---------------------------------------------------------------------------
# Allocation
# ---------------------------------------------------------------------------

def _prettify_sector_key(key: str) -> str:
    """yfinance sector_weightings keys are snake_case ('financial_services') —
    prettify for chart labels ('Financial Services')."""
    return key.replace("_", " ").title()


# Yahoo Finance stores the country of an instrument/fund as free text (often
# "US", sometimes "United States"). Grouping it here keeps the dashboard
# allocation useful without needing a separate country-weighting data source.
_CONTINENTS_BY_COUNTRY = {
    "Argentina": "South America", "Brazil": "South America", "Canada": "North America",
    "Chile": "South America", "Colombia": "South America", "Mexico": "North America",
    "United States": "North America", "US": "North America", "USA": "North America",
    "Austria": "Europe", "Belgium": "Europe", "Denmark": "Europe", "Finland": "Europe",
    "France": "Europe", "Germany": "Europe", "Ireland": "Europe", "Italy": "Europe",
    "Luxembourg": "Europe", "Netherlands": "Europe", "Norway": "Europe", "Poland": "Europe",
    "Portugal": "Europe", "Spain": "Europe", "Sweden": "Europe", "Switzerland": "Europe",
    "United Kingdom": "Europe", "UK": "Europe", "England": "Europe",
    "België": "Europe", "Duitsland": "Europe", "Frankrijk": "Europe", "Ierland": "Europe",
    "Italië": "Europe", "Nederland": "Europe", "Spanje": "Europe", "Verenigd Koninkrijk": "Europe",
    "Australia": "Oceania", "New Zealand": "Oceania",
    "China": "Asia", "Hong Kong": "Asia", "India": "Asia", "Indonesia": "Asia",
    "Japan": "Asia", "Malaysia": "Asia", "Singapore": "Asia", "South Korea": "Asia",
    "Taiwan": "Asia", "Thailand": "Asia", "Vietnam": "Asia", "Zuid-Korea": "Asia",
    "Israel": "Asia", "Saudi Arabia": "Asia", "United Arab Emirates": "Asia",
    "Egypt": "Africa", "Morocco": "Africa", "Nigeria": "Africa", "South Africa": "Africa",
    "Verenigde Staten": "North America", "Canada": "North America", "Brazilië": "South America",
    "Zuid-Afrika": "Africa",
}


def _continent_for_region(region: str | None) -> str:
    """Return a dashboard continent label for an instrument's region/country."""
    if not region:
        return "Unclassified"
    normalized = region.strip()
    if not normalized:
        return "Unclassified"
    if normalized.lower() in {"global", "worldwide", "international"}:
        return "Global"
    return _CONTINENTS_BY_COUNTRY.get(normalized, normalized)


def _pct(value) -> str:
    """Format a fraction-or-percent Decimal/float as a fixed 2-decimal percentage string."""
    return str(Decimal(str(value)).quantize(_TWO, ROUND_HALF_UP))


def _get_country_weights(conn: sqlite3.Connection, instrument_id: int) -> list[tuple[str, Decimal]]:
    """Return manual country weights as decimal percentages for an instrument."""
    rows = conn.execute(
        "SELECT country, weight_pct FROM instrument_country_weights WHERE instrument_id=?",
        (instrument_id,),
    ).fetchall()
    return [(r["country"], _d(r["weight_pct"])) for r in rows]


# The dashboard's categorical chart palette has 12 fixed hue slots (see
# app.js CHART_PALETTE) that are never cycled — a 13th bucket would otherwise
# repeat an earlier bucket's color. 12 covers every realistic case (11
# GICS-style sectors from ETF weightings + Cash; region/asset_type never
# come close) — this cap is a safety net for the rare portfolio that also
# has an Unclassified remainder on top, not the normal path.
_MAX_ALLOC_SLICES = 12


def _fold_small_buckets(groups: dict[str, list[dict]], cap: int = _MAX_ALLOC_SLICES) -> dict[str, list[dict]]:
    if len(groups) <= cap:
        return groups
    ranked = sorted(groups.items(), key=lambda item: -sum((r["value"] for r in item[1]), _ZERO))
    kept = dict(ranked[:cap - 1])
    tail_rows = [row for _, rows in ranked[cap - 1:] for row in rows]
    kept["Overig"] = kept.get("Overig", []) + tail_rows
    return kept


def get_allocation_details(
    conn: sqlite3.Connection,
    account_id: int | None = None,
) -> dict[str, dict[str, list[dict]]]:
    """Return the position-level composition behind every allocation bucket."""
    from .prices import get_fund_data_cached

    details: dict[str, dict[str, list[dict]]] = {
        "sector": defaultdict(list),
        "region": defaultdict(list),
        "asset_type": defaultdict(list),
    }

    def add(kind: str, bucket: str, holding, value: Decimal, note: str = "") -> None:
        details[kind][bucket].append({
            "instrument_id": holding.instrument.id if holding else None,
            "instrument_name": holding.instrument.name if holding else "Kas",
            "isin": holding.instrument.isin if holding else None,
            "symbol": holding.instrument.symbol if holding else None,
            "account_name": holding.account_name if holding else "Alle accounts",
            "value": value,
            "note": note,
        })

    for h in get_holdings(conn, account_id):
        val = h.current_value or h.cost_basis or _ZERO
        fund = get_fund_data_cached(conn, h.instrument.id)

        country_weights = _get_country_weights(conn, h.instrument.id)
        if country_weights:
            allocated = _ZERO
            for country, weight_pct in country_weights:
                portion = (val * weight_pct / 100).quantize(_TWO, ROUND_HALF_UP)
                if portion == 0:
                    continue
                add("region", _continent_for_region(country), h, portion, f"{country} · {_pct(weight_pct)}%")
                allocated += portion
            remainder = val - allocated
            if remainder:
                add("region", "Unclassified", h, remainder, "Niet handmatig toegewezen")
        else:
            add("region", _continent_for_region(h.instrument.region), h, val)

        add("asset_type", h.instrument.asset_type or "other", h, val)

        weightings = fund["sector_weightings"] if fund else None
        if weightings:
            allocated = _ZERO
            for key, weight in weightings.items():
                portion = (val * Decimal(str(weight))).quantize(_TWO, ROUND_HALF_UP)
                if portion == 0:
                    continue
                add("sector", _prettify_sector_key(key), h, portion,
                    f"ETF-weging: {_pct(Decimal(str(weight)) * 100)}%")
                allocated += portion
            remainder = val - allocated
            if remainder:
                add("sector", "Unclassified", h, remainder, "Niet toegewezen")
        else:
            add("sector", h.instrument.sector or "Unclassified", h, val)

    cash = get_cash_balance(conn, account_id)
    if cash:
        for kind, bucket in (("sector", "Cash"), ("region", "Cash"), ("asset_type", "cash")):
            add(kind, bucket, None, cash)

    return {
        kind: {
            bucket: sorted(rows, key=lambda row: -row["value"])
            for bucket, rows in _fold_small_buckets(groups).items()
        }
        for kind, groups in details.items()
    }


def get_allocation(
    conn: sqlite3.Connection,
    account_id: int | None = None,
) -> dict:
    """Return allocation totals: sector, continent, asset_type.

    Instruments without a value in the group-by field → "Unclassified".
    Uninvested cash is included as its own "Cash" / "cash" bucket.

    For ETFs/funds with cached sector weightings (see services.prices
    refresh_fund_data), the holding's value is split proportionally across
    its actual sectors instead of lumped into one bucket — a global-equity
    ETF genuinely holds many sectors at once, so one label was never
    accurate, just a placeholder ("Unclassified" or the fund's category).
    """
    details = get_allocation_details(conn, account_id)
    return {
        kind: dict(sorted(
            ((bucket, sum((row["value"] for row in rows), _ZERO)) for bucket, rows in groups.items()),
            key=lambda item: -item[1],
        ))
        for kind, groups in details.items()
    }


# ---------------------------------------------------------------------------
# Per-holding value over time
# ---------------------------------------------------------------------------

def get_holdings_value_series(
    conn: sqlite3.Connection,
    account_id: int | None = None,
) -> dict[str, list[dict]]:
    """Per-holding (account+instrument) value AND unrealized-P/L over time.

    Keyed by "{account_id}:{instrument_id}". Each point is
    {"date", "value", "unrealized_pl"}, where unrealized_pl = value minus
    the RUNNING average cost basis as it stood on that date (not today's
    final average cost — so buying more later doesn't retroactively change
    earlier points). Unlike a raw value delta, unrealized_pl is naturally
    unaffected by simply buying more of a position: the purchase adds the
    same amount to both value and cost basis, so it nets to zero instead of
    masquerading as a gain.
    """
    holdings = get_holdings(conn, account_id)
    result: dict[str, list[dict]] = {}
    for h in holdings:
        price_rows = conn.execute(
            "SELECT date, close FROM prices WHERE instrument_id=? ORDER BY date",
            (h.instrument.id,),
        ).fetchall()
        if not price_rows:
            continue
        txn_rows = conn.execute(
            "SELECT ts, CAST(quantity AS REAL) AS qty, CAST(value_eur AS REAL) AS value_eur, "
            "CAST(fees_eur AS REAL) AS fees_eur "
            "FROM transactions WHERE account_id=? AND instrument_id=? ORDER BY ts",
            (h.account_id, h.instrument.id),
        ).fetchall()

        series = []
        txn_idx = 0
        cum_qty = _ZERO
        cum_cost = _ZERO
        for prow in price_rows:
            date_cutoff = f"{prow['date']}T23:59:59"
            while txn_idx < len(txn_rows) and txn_rows[txn_idx]["ts"] <= date_cutoff:
                t = txn_rows[txn_idx]
                quantity = Decimal(str(t["qty"]))
                value = Decimal(str(t["value_eur"]))
                fees = Decimal(str(t["fees_eur"] or 0))
                if quantity > _ZERO:
                    cum_qty += quantity
                    cum_cost += -(value + fees)
                elif quantity < _ZERO and cum_qty > _ZERO:
                    sold = min(-quantity, cum_qty)
                    cum_cost -= (cum_cost / cum_qty) * sold
                    cum_qty -= sold
                    if abs(cum_qty) < Decimal("0.000001"):
                        cum_qty = _ZERO
                        cum_cost = _ZERO
                txn_idx += 1
            if abs(cum_qty) > Decimal("0.000001"):
                qty = cum_qty
                price = _d(prow["close"])
                value = qty * price
                unrealized = value - cum_cost
                series.append({
                    "date": prow["date"],
                    "value": str(value.quantize(_TWO, ROUND_HALF_UP)),
                    "unrealized_pl": str(unrealized.quantize(_TWO, ROUND_HALF_UP)),
                })
        if series:
            result[f"{h.account_id}:{h.instrument.id}"] = series
    return result


def get_unrealized_pl_series(
    conn: sqlite3.Connection,
    account_id: int | None = None,
) -> list[dict]:
    """Portfolio-wide unrealized P/L over time (value minus running avg-cost).

    Mirrors get_portfolio_value_series's date/holdings-as-of-date logic, but
    tracks cost basis too, and deliberately excludes cash — unrealized P/L
    only concerns invested positions, and this makes the figure immune to
    both cash-snapshot jumps and deposit/withdrawal timing by construction
    (buying more adds equally to value and cost basis, netting to zero).
    """
    date_rows = conn.execute("SELECT DISTINCT date FROM prices ORDER BY date").fetchall()
    dates = [r["date"] for r in date_rows]
    if not dates:
        return []

    result = []
    for d in dates:
        states, _ = _position_accounting(conn, account_id, f"{d}T23:59:59")

        total_unrealized = _ZERO
        any_holding = False
        for (_, instrument_id), state in states.items():
            qty = state["quantity"]
            if abs(qty) < Decimal("0.000001"):
                continue
            price_row = conn.execute(
                "SELECT close FROM prices WHERE instrument_id=? AND date<=? ORDER BY date DESC LIMIT 1",
                (instrument_id, d),
            ).fetchone()
            if not price_row:
                continue
            any_holding = True
            value = qty * _d(price_row["close"])
            total_unrealized += value - state["cost"]

        if any_holding:
            result.append({"date": d, "value": str(total_unrealized.quantize(_TWO, ROUND_HALF_UP))})

    return result




# ---------------------------------------------------------------------------
# Portfolio value over time
# ---------------------------------------------------------------------------

def get_portfolio_value_series(
    conn: sqlite3.Connection,
    account_id: int | None = None,
    start: str | None = None,
) -> list[dict]:
    """Build a daily portfolio value series from transaction history + cached prices.

    Returns list of {"date": "yyyy-mm-dd", "value": Decimal}.
    Only includes dates for which we have price data for at least one instrument.
    """
    # Get all dates for which we have any price data
    if start:
        date_rows = conn.execute(
            "SELECT DISTINCT date FROM prices WHERE date >= ? ORDER BY date", (start,)
        ).fetchall()
    else:
        date_rows = conn.execute(
            "SELECT DISTINCT date FROM prices ORDER BY date"
        ).fetchall()
    dates = [r["date"] for r in date_rows]
    if not dates:
        return []

    # For each date, calculate total portfolio value
    result = []
    for d in dates:
        # Get holdings as-of-date (instruments held at close of that day)
        sql = """
            SELECT instrument_id, SUM(CAST(quantity AS REAL)) AS qty
            FROM transactions
            WHERE ts <= ? AND (? IS NULL OR account_id = ?)
            GROUP BY instrument_id
            HAVING ABS(SUM(CAST(quantity AS REAL))) > 0.000001
        """
        holdings = conn.execute(sql, (f"{d}T23:59:59", account_id, account_id)).fetchall()

        total = _ZERO
        for h in holdings:
            price_row = conn.execute(
                "SELECT close FROM prices WHERE instrument_id=? AND date<=? ORDER BY date DESC LIMIT 1",
                (h["instrument_id"], d),
            ).fetchone()
            if price_row:
                total += Decimal(str(h["qty"])) * _d(price_row["close"])

        # Cash snapshots are end-of-day values. Apply later activity up to
        # this chart date, so an incremental import neither loses cash nor
        # double-counts sale proceeds that were subsequently reinvested.
        snap_sql = """
            SELECT account_id, balance_eur, date
            FROM (
                SELECT bs.account_id, bs.balance_eur, bs.date,
                       ROW_NUMBER() OVER (PARTITION BY bs.account_id ORDER BY bs.date DESC, bs.id DESC) AS rn
                FROM balance_snapshots bs
                JOIN accounts a ON a.id=bs.account_id
                WHERE bs.date <= ? AND a.type != 'savings'
                  AND (? IS NULL OR bs.account_id = ?)
            ) latest
            WHERE rn = 1
        """
        for snap in conn.execute(snap_sql, (d, account_id, account_id)).fetchall():
            total += _cash_balance_from_snapshot(
                conn,
                snap["account_id"],
                snap["date"],
                Decimal(str(snap["balance_eur"])),
                through_date=d,
            )

        if total > _ZERO:
            result.append({"date": d, "value": total.quantize(_TWO, ROUND_HALF_UP)})

    return result


# ---------------------------------------------------------------------------
# Summary stats for dashboard
# ---------------------------------------------------------------------------

def get_portfolio_summary(
    conn: sqlite3.Connection,
    account_id: int | None = None,
) -> dict:
    """Return high-level summary dict for the dashboard."""
    holdings = get_holdings(conn, account_id)
    holdings_value = sum(h.current_value for h in holdings if h.current_value) or _ZERO
    cash_balance = get_cash_balance(conn, account_id)
    total_value = holdings_value + cash_balance
    total_cost = sum(h.cost_basis for h in holdings) or _ZERO
    unrealized = sum(h.unrealized_pl for h in holdings if h.unrealized_pl) or _ZERO
    unrealized_pct = (unrealized / total_cost * 100).quantize(_TWO) if total_cost else _ZERO
    realized = get_realized_pl(conn, account_id)

    # Net deposits = external cash moved into/out of the account (deposit -
    # withdrawal cash_events; withdrawal amounts are stored negative). This is
    # the "wat heb ik erin gestopt" baseline for total wealth growth — unlike
    # total_cost/total transaction cost above, it also captures dividends,
    # interest and fees that never touch a buy/sell transaction, and unlike
    # a naive value-minus-deposits it isn't thrown off by withdrawals (taking
    # profit out isn't a loss).
    deposits_row = conn.execute(
        """SELECT SUM(CAST(ce.amount_eur AS REAL)) AS net
           FROM cash_events ce
           JOIN accounts a ON a.id = ce.account_id
           WHERE ce.type IN ('deposit','withdrawal')
             AND a.type != 'savings'
             AND (:acct IS NULL OR ce.account_id = :acct)""",
        {"acct": account_id},
    ).fetchone()
    net_deposits = Decimal(str(deposits_row["net"])) if deposits_row and deposits_row["net"] else _ZERO
    total_pl = (total_value - net_deposits).quantize(_TWO, ROUND_HALF_UP)
    total_pl_pct = (total_pl / net_deposits * 100).quantize(_TWO) if net_deposits else _ZERO

    # Prices-as-of: most recent price date across all instruments
    price_date_row = conn.execute(
        "SELECT MAX(date) AS max_date FROM prices"
    ).fetchone()
    price_as_of = price_date_row["max_date"] if price_date_row else None

    return {
        "total_value": total_value,
        "holdings_value": holdings_value,
        "cash_balance": cash_balance,
        "total_cost": total_cost,
        "unrealized_pl": unrealized,
        "unrealized_pl_pct": unrealized_pct,
        "realized_pl": realized,
        "total_pl": total_pl,
        "total_pl_pct": total_pl_pct,
        "net_deposits": net_deposits,
        "holdings_count": len(holdings),
        "price_as_of": price_as_of,
        "has_stale_prices": price_as_of is None or (len(holdings) > 0 and price_as_of < str(_date.today())),
    }


# ---------------------------------------------------------------------------
# Closed positions
# ---------------------------------------------------------------------------

def get_closed_positions(
    conn: sqlite3.Connection,
    account_id: int | None = None,
) -> list[dict]:
    """Return fully-closed positions (net qty ≈ 0) with realized P/L per instrument."""
    sql = """
        SELECT
            t.account_id,
            a.name                                                          AS account_name,
            t.instrument_id,
            SUM(CAST(t.quantity  AS REAL))                                  AS net_qty,
            SUM(CASE WHEN CAST(t.quantity AS REAL) > 0
                     THEN (CAST(t.value_eur AS REAL) + CAST(t.fees_eur AS REAL)) * -1 ELSE 0 END) AS buy_eur,
            SUM(CASE WHEN CAST(t.quantity AS REAL) < 0
                     THEN CAST(t.value_eur AS REAL) + CAST(t.fees_eur AS REAL) ELSE 0 END)        AS sell_eur,
            SUM(CASE WHEN CAST(t.quantity AS REAL) > 0
                     THEN CAST(t.quantity AS REAL)      ELSE 0 END)        AS buy_qty,
            SUM(CASE WHEN CAST(t.quantity AS REAL) < 0
                     THEN ABS(CAST(t.quantity AS REAL)) ELSE 0 END)        AS sell_qty,
            MIN(t.ts)                                                       AS first_ts,
            MAX(t.ts)                                                       AS last_ts
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        WHERE (:acct IS NULL OR t.account_id = :acct)
        GROUP BY t.account_id, t.instrument_id
        HAVING ABS(SUM(CAST(t.quantity AS REAL))) < 0.000001
           AND SUM(CASE WHEN CAST(t.quantity AS REAL) < 0
                        THEN ABS(CAST(t.quantity AS REAL)) ELSE 0 END) > 0
        ORDER BY MAX(t.ts) DESC
    """
    rows = conn.execute(sql, {"acct": account_id}).fetchall()
    _, sale_events = _position_accounting(conn, account_id)
    events_by_position: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for event in sale_events:
        events_by_position[(event["account_id"], event["instrument_id"])].append(event)
    result: list[dict] = []
    for r in rows:
        irow = conn.execute(
            "SELECT id,isin,name,symbol,exchange,currency,trading_currency,asset_type,sector,region "
            "FROM instruments WHERE id=?",
            (r["instrument_id"],),
        ).fetchone()
        if not irow:
            continue

        position_events = events_by_position[(r["account_id"], r["instrument_id"])]
        sell_eur = sum((event["proceeds"] for event in position_events), _ZERO)
        realized_pl = sum((event["realized_pl"] for event in position_events), _ZERO).quantize(_TWO, ROUND_HALF_UP)
        cost_of_sold = (sell_eur - realized_pl).quantize(_TWO, ROUND_HALF_UP)
        buy_eur = cost_of_sold
        realized_pct = (
            (realized_pl / cost_of_sold * 100).quantize(_TWO, ROUND_HALF_UP)
            if cost_of_sold else _ZERO
        )

        result.append({
            "instrument":    _row_to_instrument(irow),
            "account_name":  r["account_name"],
            "buy_eur":       buy_eur,
            "sell_eur":      sell_eur,
            "realized_pl":   realized_pl,
            "realized_pl_pct": realized_pct,
            "opened":        r["first_ts"][:10] if r["first_ts"] else None,
            "closed":        r["last_ts"][:10]  if r["last_ts"]  else None,
        })

    return result
