"""Parser for DeGiro Transactions.csv (Transacties export).

Column structure (map by header name, NOT by index):
  Datum, Tijd, Product, ISIN, Beurs, Uitvoeringsplaats,
  Aantal, Koers, [ccy], Lokale waarde, [ccy], Waarde, [ccy],
  Wisselkoers, Transactiekosten en/of, [ccy], Totaal, [ccy], Order ID

The unnamed columns after each amount column hold the currency code for
that amount.  We resolve them via ColumnIndex.get_next().
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from . import (
    ColumnIndex,
    parse_dutch_date,
    parse_dutch_decimal,
    read_csv_rows,
    row_hash,
)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

REQUIRED_HEADERS = {"Datum", "Aantal", "Koers", "ISIN", "Order ID"}


def is_transactions_csv(content: str) -> bool:
    """Return True if the content looks like a DeGiro Transactions export.

    Requires BOTH 'Aantal' and 'Koers' — these are transaction-specific columns
    that are absent from the account statement (Rekeningoverzicht).
    Checking only 'Order ID' is insufficient: the account statement also has it.
    """
    from . import strip_bom
    first_line = strip_bom(content).split("\n")[0]
    return "Aantal" in first_line and "Koers" in first_line


# ---------------------------------------------------------------------------
# Row result
# ---------------------------------------------------------------------------

@dataclass
class TxnRow:
    ts: str
    product: str
    isin: str
    exchange: str
    quantity: Decimal
    price: Decimal
    price_currency: str
    local_value: Decimal
    local_currency: str
    value_eur: Decimal
    fx_rate: Optional[Decimal]
    fees_eur: Decimal
    order_id: Optional[str]
    dedup_hash: str


@dataclass
class TransactionParseResult:
    rows: list[TxnRow] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse(content: str) -> TransactionParseResult:
    col, data_rows = read_csv_rows(content)
    result = TransactionParseResult()

    for raw_row in data_rows:
        try:
            row = _parse_row(col, raw_row)
            if row is not None:
                result.rows.append(row)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"Row {raw_row!r}: {exc}")

    return result


def _parse_row(col: ColumnIndex, raw: list[str]) -> Optional[TxnRow]:
    datum = col.get(raw, "Datum")
    tijd = col.get(raw, "Tijd")
    if not datum:
        return None  # skip empty rows

    date_iso = parse_dutch_date(datum)
    ts = f"{date_iso}T{tijd}:00" if tijd else f"{date_iso}T00:00:00"

    quantity_str = col.get(raw, "Aantal")
    quantity = parse_dutch_decimal(quantity_str)

    price_str = col.get(raw, "Koers")
    price = parse_dutch_decimal(price_str)
    price_currency = col.get_next(raw, "Koers") or "EUR"

    local_value = parse_dutch_decimal(col.get(raw, "Lokale waarde"))
    local_currency = col.get_next(raw, "Lokale waarde") or price_currency

    value_eur = parse_dutch_decimal(col.get(raw, "Waarde"))

    fx_str = col.get(raw, "Wisselkoers")
    fx_rate = parse_dutch_decimal(fx_str) if fx_str else None

    fees_str = col.get(raw, "Transactiekosten en/of")
    fees_eur = parse_dutch_decimal(fees_str) if fees_str else Decimal("0")

    order_id = col.get(raw, "Order ID") or None

    isin = col.get(raw, "ISIN")
    product = col.get(raw, "Product")
    exchange = col.get(raw, "Beurs") or col.get(raw, "Uitvoeringsplaats") or ""

    hash_val = row_hash(raw)

    return TxnRow(
        ts=ts,
        product=product,
        isin=isin,
        exchange=exchange,
        quantity=quantity,
        price=price,
        price_currency=price_currency,
        local_value=local_value,
        local_currency=local_currency,
        value_eur=value_eur,
        fx_rate=fx_rate,
        fees_eur=fees_eur,
        order_id=order_id,
        dedup_hash=hash_val,
    )


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_or_create_instrument(conn: sqlite3.Connection, isin: str, name: str,
                              exchange: str | None = None) -> int:
    """Return instrument_id, creating the row if it does not exist yet."""
    row = conn.execute(
        "SELECT id FROM instruments WHERE isin=?", (isin,)
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO instruments(isin, name, exchange) VALUES (?,?,?)",
        (isin, name, exchange or None),
    )
    return cur.lastrowid  # type: ignore[return-value]


def commit_transactions(
    conn: sqlite3.Connection,
    parse_result: TransactionParseResult,
    account_id: int,
) -> tuple[int, int, list[str]]:
    """Insert new transaction rows; skip duplicates.

    Returns (imported, skipped, errors).
    """
    imported = skipped = 0
    errors = list(parse_result.errors)

    for txn in parse_result.rows:
        try:
            instrument_id = get_or_create_instrument(
                conn, txn.isin, txn.product, txn.exchange
            )
            try:
                conn.execute(
                    """INSERT INTO transactions
                       (account_id, instrument_id, ts, quantity, price,
                        local_currency, fx_rate, value_eur, fees_eur,
                        order_id, source)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        account_id,
                        instrument_id,
                        txn.ts,
                        str(txn.quantity),
                        str(txn.price),
                        txn.local_currency,
                        str(txn.fx_rate) if txn.fx_rate is not None else None,
                        str(txn.value_eur),
                        str(txn.fees_eur),
                        txn.order_id,
                        "degiro_csv",
                    ),
                )
                imported += 1
            except Exception as dup_exc:
                if "UNIQUE" in str(dup_exc):
                    skipped += 1
                else:
                    raise
        except Exception as exc:  # noqa: BLE001
            errors.append(f"DB insert error for {txn.isin}: {exc}")

    return imported, skipped, errors
