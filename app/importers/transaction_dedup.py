"""Stable transaction deduplication across changing CSV exports."""
from __future__ import annotations

import sqlite3
from decimal import Decimal


def is_duplicate_transaction(
    conn: sqlite3.Connection,
    account_id: int,
    instrument_id: int,
    order_id: str | None,
    ts: str,
    quantity: Decimal,
    price: Decimal,
    local_currency: str,
    *,
    dedup_hash: str | None = None,
    occurrence: int = 1,
) -> bool:
    """Whether this occurrence already exists in the stored history.

    The raw-row hash is a fast exact match, but is not stable when a broker
    changes CSV language, formatting or balance fields. The semantic count
    keeps genuinely repeated fills: occurrence two is only a duplicate when
    two matching transactions are already stored.
    """
    if dedup_hash and conn.execute(
        "SELECT 1 FROM transactions WHERE dedup_hash=? LIMIT 1", (dedup_hash,)
    ).fetchone():
        return True

    count = conn.execute(
        """SELECT COUNT(*) FROM transactions
           WHERE account_id=? AND instrument_id=? AND ts=?
             AND CAST(quantity AS NUMERIC)=CAST(? AS NUMERIC)
             AND CAST(price AS NUMERIC)=CAST(? AS NUMERIC)
             AND local_currency=?
             AND ((order_id=? ) OR (order_id IS NULL AND ? IS NULL))""",
        (
            account_id,
            instrument_id,
            ts,
            str(quantity),
            str(price),
            local_currency,
            order_id,
            order_id,
        ),
    ).fetchone()[0]
    return count >= occurrence
