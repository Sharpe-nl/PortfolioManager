"""Shared instrument resolution for CSV importers."""
from __future__ import annotations

import sqlite3


def get_or_create_isin_instrument(
    conn: sqlite3.Connection,
    isin: str,
    name: str,
    trading_currency: str | None = None,
) -> int:
    """Resolve an ISIN without ever splitting an established stock.

    Non-stock instruments may have distinct trading lines per currency. Stocks
    represent one holding per ISIN, while a legacy line without a trading
    currency is claimed by the first import that supplies one.
    """
    if trading_currency:
        row = conn.execute(
            "SELECT id FROM instruments WHERE isin=? AND trading_currency=?",
            (isin, trading_currency),
        ).fetchone()
        if row:
            return row["id"]
    else:
        row = conn.execute(
            "SELECT id FROM instruments WHERE isin=? ORDER BY id LIMIT 1", (isin,)
        ).fetchone()
        if row:
            return row["id"]

    stock = conn.execute(
        "SELECT id FROM instruments WHERE isin=? AND asset_type='stock' "
        "ORDER BY id LIMIT 1",
        (isin,),
    ).fetchone()
    if stock:
        return stock["id"]

    unassigned = conn.execute(
        "SELECT id FROM instruments WHERE isin=? AND trading_currency IS NULL "
        "ORDER BY id LIMIT 1",
        (isin,),
    ).fetchone()
    if unassigned:
        if trading_currency:
            conn.execute(
                "UPDATE instruments SET trading_currency=? WHERE id=?",
                (trading_currency, unassigned["id"]),
            )
        return unassigned["id"]

    cur = conn.execute(
        "INSERT INTO instruments(isin, name, trading_currency) VALUES (?,?,?)",
        (isin, name, trading_currency),
    )
    return cur.lastrowid  # type: ignore[return-value]
