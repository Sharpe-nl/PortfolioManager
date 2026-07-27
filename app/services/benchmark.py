"""Benchmark comparison and XIRR calculation.

Method: "same cash flows into benchmark" — every deposit/withdrawal is
replayed as a hypothetical purchase/sale of the benchmark instrument at
the closing price on that day.  Produces a fair comparison for portfolios
with ongoing contributions.

XIRR is implemented with Newton-Raphson (no scipy).
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from .prices import refresh_history, YFinanceProvider

_ZERO = Decimal("0")
_TWO = Decimal("0.01")
_provider = YFinanceProvider()


def _d(s: str | None) -> Decimal:
    try:
        value = Decimal(s) if s else _ZERO
    except Exception:
        return _ZERO
    return value if value.is_finite() else _ZERO


# ---------------------------------------------------------------------------
# XIRR
# ---------------------------------------------------------------------------

def xirr(cash_flows: list[tuple[str, Decimal]], guess: float = 0.1) -> Optional[float]:
    """Calculate XIRR for irregular cash flows.

    cash_flows: [(date_iso, amount), ...]
        Negative amount = outflow (investment), positive = inflow (return).
    Returns annual rate as float, or None if convergence fails.
    """
    if not cash_flows:
        return None

    dates_d = [date.fromisoformat(d) for d, _ in cash_flows]
    amounts = [float(a) for _, a in cash_flows]
    t0 = dates_d[0]
    t = [(dd - t0).days / 365.0 for dd in dates_d]

    def npv(r: float) -> float:
        return sum(c / (1 + r) ** ti for c, ti in zip(amounts, t))

    def d_npv(r: float) -> float:
        return sum(-ti * c / (1 + r) ** (ti + 1) for c, ti in zip(amounts, t))

    rate = guess
    for _ in range(200):
        try:
            npv_val = npv(rate)
            d_val = d_npv(rate)
            if abs(d_val) < 1e-14:
                break
            new_rate = rate - npv_val / d_val
            if abs(new_rate - rate) < 1e-7:
                return new_rate
            rate = new_rate
            if rate <= -1:
                rate = -0.999
        except (OverflowError, ZeroDivisionError):
            break
    return None


# ---------------------------------------------------------------------------
# Benchmark price helpers
# ---------------------------------------------------------------------------

def _get_benchmark_id(conn: sqlite3.Connection, ticker: str) -> int:
    """Get or create an instruments row for the benchmark ticker."""
    row = conn.execute(
        "SELECT id FROM instruments WHERE symbol=?", (ticker,)
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO instruments(name, symbol) VALUES (?,?)",
        (f"Benchmark: {ticker}", ticker),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def _price_on_or_before(
    conn: sqlite3.Connection, instrument_id: int, target_date: str,
) -> Optional[Decimal]:
    row = conn.execute(
        "SELECT close FROM prices WHERE instrument_id=? AND date<=? ORDER BY date DESC LIMIT 1",
        (instrument_id, target_date),
    ).fetchone()
    return _d(row["close"]) if row else None


# ---------------------------------------------------------------------------
# Main comparison
# ---------------------------------------------------------------------------

def get_deposits_and_portfolio_series(
    conn: sqlite3.Connection,
    account_id: int | None = None,
):
    """External cash flows + portfolio value series — independent of any benchmark
    ticker. Exposed publicly so a caller comparing against several
    benchmarks at once (e.g. the benchmark page with multiple ticked boxes)
    can compute this once and pass it into get_benchmark_comparison via
    `_shared`, instead of recomputing the (DB-heavy) portfolio value series
    once per benchmark.

    Returns (first_date, cash_flow_rows, port_series), or (None, [], []) if
    there are no external cash flows yet. Withdrawals are stored as negative
    amounts and must be replayed as a partial benchmark sale.
    """
    dep_sql = """
        SELECT ts, amount_eur FROM cash_events
        WHERE type IN ('deposit', 'withdrawal')
          AND (:acct IS NULL OR account_id = :acct)
        ORDER BY ts
    """
    cash_flows = conn.execute(dep_sql, {"acct": account_id}).fetchall()
    if not cash_flows:
        return None, [], []

    first_date = cash_flows[0]["ts"][:10]
    from .portfolio import get_portfolio_value_series
    port_series = get_portfolio_value_series(conn, account_id, start=first_date)
    return first_date, cash_flows, port_series


def get_benchmark_comparison(
    conn: sqlite3.Connection,
    benchmark_ticker: str,
    account_id: int | None = None,
    _shared: tuple | None = None,
) -> dict:
    """Return benchmark comparison data.

    Returns dict with:
      - portfolio_series:   list[{"date", "value"}]
      - benchmark_series:   list[{"date", "value"}]
      - portfolio_xirr:     float | None (as %)
      - benchmark_xirr:     float | None (as %)
      - portfolio_return:   Decimal (%)
      - benchmark_return:   Decimal (%)
      - stale:              bool

    `_shared`: optional pre-computed get_deposits_and_portfolio_series()
    result, to avoid recomputing it when comparing against several
    benchmarks for the same account in one request.
    """
    if _shared is not None:
        first_date, cash_flows, port_series = _shared
    else:
        first_date, cash_flows, port_series = get_deposits_and_portfolio_series(conn, account_id)
    if first_date is None:
        return _empty_result()

    # Ensure benchmark prices are cached
    today_str = str(date.today())
    bench_id = _get_benchmark_id(conn, benchmark_ticker)
    refresh_history(conn, bench_id, benchmark_ticker, first_date, today_str, provider=_provider)

    # Build the hypothetical benchmark position by replaying every external
    # cash flow at its own date's price. A withdrawal has a negative amount,
    # so it sells benchmark shares instead of leaving the original deposit
    # invested forever.
    flow_shares: list[tuple[str, Decimal]] = []
    cash_flows_bench: list[tuple[str, Decimal]] = []
    cash_flows_portfolio: list[tuple[str, Decimal]] = []

    for flow in cash_flows:
        flow_date = flow["ts"][:10]
        amount = _d(flow["amount_eur"])
        bench_price = _price_on_or_before(conn, bench_id, flow_date)
        shares = (amount / bench_price) if bench_price and bench_price > 0 else _ZERO
        flow_shares.append((flow_date, shares))
        # Deposits are outflows and withdrawals inflows for XIRR. Reversing
        # the stored signed cash amount gives exactly that convention.
        cash_flows_bench.append((flow_date, -amount))
        cash_flows_portfolio.append((flow_date, -amount))

    bench_shares = sum((s for _, s in flow_shares), _ZERO)

    # Current benchmark value
    bench_price_now = _price_on_or_before(conn, bench_id, today_str)
    bench_value_now = (bench_shares * bench_price_now).quantize(_TWO) if bench_price_now else _ZERO

    # Current portfolio value
    port_value_now = port_series[-1]["value"] if port_series else _ZERO

    # XIRR: add final value as inflow
    if bench_value_now > 0 and cash_flows_bench:
        cash_flows_bench.append((today_str, bench_value_now))
    if port_value_now > 0 and cash_flows_portfolio:
        cash_flows_portfolio.append((today_str, port_value_now))

    port_xirr = xirr(cash_flows_portfolio)
    bench_xirr = xirr(cash_flows_bench)

    # Build benchmark value series (same date points as portfolio) — at each
    # date, only count shares from cash flows made on or before that date.
    bench_series = []
    for pt in port_series:
        shares_as_of = sum((s for d, s in flow_shares if d <= pt["date"]), _ZERO)
        bp = _price_on_or_before(conn, bench_id, pt["date"])
        bv = (shares_as_of * bp).quantize(_TWO) if bp else _ZERO
        bench_series.append({"date": pt["date"], "value": bv})

    # Total returns
    total_invested = sum(_d(flow["amount_eur"]) for flow in cash_flows)
    port_return = (
        ((port_value_now - total_invested) / total_invested * 100).quantize(_TWO)
        if total_invested else _ZERO
    )
    bench_return = (
        ((bench_value_now - total_invested) / total_invested * 100).quantize(_TWO)
        if total_invested else _ZERO
    )

    return {
        "portfolio_series": port_series,
        "benchmark_series": bench_series,
        # Raw external cash flows (date, signed amount) — the same flows feed both the
        # portfolio and the hypothetical benchmark by construction, so the
        # client can recompute return% / XIRR for an arbitrary period
        # (range selector) without a server round-trip, the same way the
        # dashboard and dividends pages already do.
        "deposits": [{"date": flow["ts"][:10], "amount_eur": str(_d(flow["amount_eur"]))} for flow in cash_flows],
        "portfolio_xirr": round(port_xirr * 100, 2) if port_xirr is not None else None,
        "benchmark_xirr": round(bench_xirr * 100, 2) if bench_xirr is not None else None,
        "portfolio_return": port_return,
        "benchmark_return": bench_return,
        "benchmark_ticker": benchmark_ticker,
        "benchmark_value": bench_value_now,
        "portfolio_value": port_value_now,
        "stale": bench_price_now is None,
    }


def _empty_result() -> dict:
    return {
        "portfolio_series": [],
        "benchmark_series": [],
        "deposits": [],
        "portfolio_xirr": None,
        "benchmark_xirr": None,
        "portfolio_return": _ZERO,
        "benchmark_return": _ZERO,
        "benchmark_ticker": "",
        "benchmark_value": _ZERO,
        "portfolio_value": _ZERO,
        "stale": True,
    }
