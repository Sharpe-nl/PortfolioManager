"""Benchmark comparison route."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse

from ..db import get_db, get_setting, set_setting
from ..helpers import templates, require_auth, optional_account_id
from ..services.benchmark import get_benchmark_comparison, get_deposits_and_portfolio_series

router = APIRouter(prefix="/benchmark", tags=["benchmark"])

PRESETS = [
    ("VWRL.AS", "Vanguard FTSE All-World (VWRL)"),
    ("IWDA.AS", "iShares Core MSCI World (IWDA)"),
    ("^GSPC",   "S&P 500 Index"),
    ("^AEX",    "AEX Index"),
]

# Fresh-load default — deliberately one of the PRESETS values above (not the
# free-text "default benchmark ticker" Settings field, which the owner can
# set to anything and might not match a checkbox here at all, leaving the
# comparison table showing a ticker with no checked box to match it).
DEFAULT_TICKER = "VWRL.AS"


@router.get("", response_class=HTMLResponse)
async def benchmark_page(
    request: Request,
    tickers: list[str] = Query(default=[]),
    submitted: str | None = None,
    account: int | None = Depends(optional_account_id),
    conn=Depends(get_db),
    _=Depends(require_auth),
):
    # `submitted` distinguishes "form was submitted with every checkbox
    # unchecked" (tickers=[], show none) from "fresh page load" (tickers=[]
    # because the query string is simply absent) — on a fresh load, restore
    # whatever was checked last time instead of always resetting to the
    # default, so the selection survives navigating away and back.
    if submitted:
        active_tickers = tickers
        set_setting(conn, "benchmark_active_tickers", json.dumps(tickers))
        conn.commit()
    else:
        saved = get_setting(conn, "benchmark_active_tickers")
        active_tickers = json.loads(saved) if saved is not None else [DEFAULT_TICKER]

    # Compute the (DB-heavy) portfolio value series once and reuse it for
    # every selected benchmark, instead of recomputing it per ticker.
    shared = get_deposits_and_portfolio_series(conn, account_id=account)
    _, deposit_rows, portfolio_series = shared
    deposits = [{"date": d["ts"][:10], "amount_eur": str(d["amount_eur"])} for d in deposit_rows]

    comparisons = {
        t: get_benchmark_comparison(conn, t, account_id=account, _shared=shared)
        for t in active_tickers
    }

    from ..services.portfolio import list_accounts
    return templates.TemplateResponse("benchmark.html", {
        "request": request,
        "comparisons": comparisons,
        "portfolio_series": portfolio_series,
        "deposits": deposits,
        "presets": PRESETS,
        "active_tickers": active_tickers,
        "accounts": [acc for acc in list_accounts(conn) if acc.type in ("broker", "pension")],
        "selected_account": account,
    })
