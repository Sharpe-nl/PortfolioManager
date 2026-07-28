"""Dividend page routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from ..db import get_db
from ..helpers import templates, require_auth, optional_account_id
from ..services import dividends as svc

router = APIRouter(prefix="/dividends", tags=["dividends"])


@router.get("", response_class=HTMLResponse)
async def dividends_page(
    request: Request,
    account: int | None = Depends(optional_account_id),
    conn=Depends(get_db),
    _=Depends(require_auth),
):
    history_yearly = svc.get_dividend_history_by_year(conn, account_id=account)
    by_instrument = svc.get_dividend_history_by_instrument(conn, account_id=account)
    trailing = svc.get_trailing_12m_income(conn, account_id=account)

    # Raw events (not bucketed) so the range selector (1M/YTD/1J/Custom/Alles)
    # can filter and re-bucket by month client-side for any arbitrary window,
    # not just a fixed last-24-months server query.
    dividend_events = svc.get_dividend_events(conn, account_id=account)
    dividend_events_detail = svc.get_dividend_events_detail(conn, account_id=account)

    from ..services.portfolio import list_accounts
    return templates.TemplateResponse("dividends.html", {
        "request": request,
        "history_yearly": history_yearly,
        "by_instrument": by_instrument,
        "trailing_12m": trailing,
        "dividend_events": dividend_events,
        "dividend_events_detail": dividend_events_detail,
        "accounts": [acc for acc in list_accounts(conn) if acc.type in ("broker", "pension")],
        "selected_account": account,
    })
