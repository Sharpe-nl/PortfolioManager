"""Actions: unified timeline of all transactions and cash events."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from ..db import get_db
from ..helpers import templates, require_auth, optional_account_id
from ..services.portfolio import list_accounts

router = APIRouter(prefix="/actions", tags=["actions"])


@router.get("", response_class=HTMLResponse)
async def actions_page(
    request: Request,
    account: int | None = Depends(optional_account_id),
    filter: str = "all",   # all | flagged | transactions | cash
    conn=Depends(get_db),
    _=Depends(require_auth),
):
    params = {"acct": account}

    # --- transactions query -------------------------------------------------
    txn_sql = """
        SELECT
            t.ts,
            t.account_id,
            a.name                  AS account_name,
            t.instrument_id,
            i.name                  AS instrument_name,
            i.isin,
            t.quantity,
            t.price,
            t.local_currency,
            t.value_eur,
            t.fees_eur,
            'transaction'           AS category,
            CASE
                WHEN CAST(t.quantity AS REAL) > 0 AND CAST(t.price AS REAL) = 0
                     THEN 'corporate'
                WHEN CAST(t.quantity AS REAL) > 0 THEN 'buy'
                ELSE 'sell'
            END                     AS action_type,
            NULL                    AS description
        FROM transactions t
        JOIN accounts    a ON a.id = t.account_id
        JOIN instruments i ON i.id = t.instrument_id
        WHERE (:acct IS NULL OR t.account_id = :acct)
    """

    # --- cash events query --------------------------------------------------
    cash_sql = """
        SELECT
            ce.ts,
            ce.account_id,
            a.name                  AS account_name,
            ce.instrument_id,
            COALESCE(i.name, '')    AS instrument_name,
            COALESCE(i.isin, '')    AS isin,
            NULL                    AS quantity,
            NULL                    AS price,
            NULL                    AS local_currency,
            ce.amount_eur           AS value_eur,
            NULL                    AS fees_eur,
            'cash_event'            AS category,
            ce.type                 AS action_type,
            ce.description
        FROM cash_events ce
        JOIN accounts    a ON a.id  = ce.account_id
        LEFT JOIN instruments i ON i.id = ce.instrument_id
        WHERE (:acct IS NULL OR ce.account_id = :acct)
    """

    flagged_txn_where  = " AND CAST(t.price AS REAL) = 0"
    flagged_cash_where = " AND ce.type = 'other'"

    def _fetch(sql: str, extra: str = "", limit: int = 500) -> list[dict]:
        order = " ORDER BY ts DESC"
        lim   = f" LIMIT {limit}"
        return [dict(r) for r in conn.execute(sql + extra + order + lim, params)]

    if filter == "transactions":
        events = _fetch(txn_sql)
    elif filter == "cash":
        events = _fetch(cash_sql)
    elif filter == "flagged":
        rows = _fetch(txn_sql, flagged_txn_where, limit=1000) + \
               _fetch(cash_sql, flagged_cash_where, limit=1000)
        events = sorted(rows, key=lambda x: x["ts"] or "", reverse=True)
    else:  # all
        rows = _fetch(txn_sql) + _fetch(cash_sql)
        events = sorted(rows, key=lambda x: x["ts"] or "", reverse=True)[:500]

    # count flagged for the badge
    flagged_count = conn.execute(
        """
        SELECT COUNT(*) AS n FROM (
            SELECT t.ts FROM transactions t
            WHERE (:acct IS NULL OR t.account_id = :acct)
              AND CAST(t.price AS REAL) = 0
            UNION ALL
            SELECT ce.ts FROM cash_events ce
            WHERE (:acct IS NULL OR ce.account_id = :acct)
              AND ce.type = 'other'
        )
        """,
        params,
    ).fetchone()["n"]

    return templates.TemplateResponse("actions.html", {
        "request":          request,
        "events":           events,
        "accounts":         list_accounts(conn),
        "selected_account": account,
        "filter":           filter,
        "flagged_count":    flagged_count,
    })
