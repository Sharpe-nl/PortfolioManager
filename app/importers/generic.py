"""Generic CSV importer and manual entry helpers.

Generic CSV format (documented in README):
  date,type,isin_or_name,quantity,price,amount_eur,description

  type: transaction | dividend | fee | deposit | withdrawal | interest | balance
  date: yyyy-mm-dd
  For 'transaction': quantity and price are required; amount_eur optional
  For cash events: amount_eur required; quantity/price optional
  For 'balance': creates a balance_snapshot row; amount_eur = balance in EUR
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from . import parse_decimal, read_csv_rows, row_hash

GENERIC_EVENT_TYPES = {
    "dividend", "fee", "deposit", "withdrawal", "interest",
}

TRANSACTION_TYPE = "transaction"
BALANCE_TYPE = "balance"


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

@dataclass
class GenericRow:
    date: str
    row_type: str          # 'transaction' | 'balance' | cash event type
    isin_or_name: str
    quantity: Optional[Decimal]
    price: Optional[Decimal]
    amount_eur: Decimal
    description: str
    dedup_hash: str


@dataclass
class GenericParseResult:
    rows: list[GenericRow] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def parse(content: str) -> GenericParseResult:
    col, data_rows = read_csv_rows(content)
    result = GenericParseResult()

    # Accept both header-based and positional (no header)
    has_date_header = col.idx("date") is not None

    for i, raw in enumerate(data_rows):
        try:
            if has_date_header:
                row = _parse_header_row(col, raw)
            else:
                row = _parse_positional_row(raw)
            if row is not None:
                result.rows.append(row)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"Row {i+2}: {exc}")

    return result


def _parse_header_row(col, raw: list[str]) -> Optional[GenericRow]:
    date = col.get(raw, "date").strip()
    if not date:
        return None
    row_type = col.get(raw, "type", "transaction").lower().strip()
    isin_or_name = col.get(raw, "isin_or_name") or col.get(raw, "isin") or col.get(raw, "name")
    qty_str = col.get(raw, "quantity")
    price_str = col.get(raw, "price")
    amt_str = col.get(raw, "amount_eur")
    description = col.get(raw, "description")
    return GenericRow(
        date=date,
        row_type=row_type,
        isin_or_name=isin_or_name,
        quantity=parse_decimal(qty_str) if qty_str else None,
        price=parse_decimal(price_str) if price_str else None,
        amount_eur=parse_decimal(amt_str) if amt_str else Decimal("0"),
        description=description,
        dedup_hash=row_hash(raw),
    )


def _parse_positional_row(raw: list[str]) -> Optional[GenericRow]:
    # date,type,isin_or_name,quantity,price,amount_eur,description
    if len(raw) < 3:
        return None
    date = raw[0].strip()
    row_type = raw[1].strip().lower() if len(raw) > 1 else "transaction"
    isin_or_name = raw[2].strip() if len(raw) > 2 else ""
    qty = parse_decimal(raw[3]) if len(raw) > 3 and raw[3].strip() else None
    price = parse_decimal(raw[4]) if len(raw) > 4 and raw[4].strip() else None
    amt = parse_decimal(raw[5]) if len(raw) > 5 and raw[5].strip() else Decimal("0")
    desc = raw[6].strip() if len(raw) > 6 else ""
    return GenericRow(
        date=date,
        row_type=row_type,
        isin_or_name=isin_or_name,
        quantity=qty,
        price=price,
        amount_eur=amt,
        description=desc,
        dedup_hash=row_hash(raw),
    )


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _get_or_create_instrument(
    conn: sqlite3.Connection,
    isin_or_name: str,
    trading_currency: str | None = None,
) -> int:
    """Resolve an ISIN within its trading currency, then create if missing."""
    # Try ISIN lookup
    if len(isin_or_name) == 12 and isin_or_name[:2].isalpha():
        if trading_currency:
            row = conn.execute(
                "SELECT id FROM instruments WHERE isin=? AND trading_currency=?",
                (isin_or_name, trading_currency),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id FROM instruments WHERE isin=? ORDER BY id LIMIT 1", (isin_or_name,)
            ).fetchone()
        if row:
            return row["id"]
        cur = conn.execute(
            "INSERT INTO instruments(isin, name, trading_currency) VALUES (?,?,?)",
            (isin_or_name, isin_or_name, trading_currency),
        )
        return cur.lastrowid  # type: ignore[return-value]
    # Name lookup
    row = conn.execute(
        "SELECT id FROM instruments WHERE name=?", (isin_or_name,)
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO instruments(name) VALUES (?)", (isin_or_name,)
    )
    return cur.lastrowid  # type: ignore[return-value]


def commit_generic_rows(
    conn: sqlite3.Connection,
    parse_result: GenericParseResult,
    account_id: int,
) -> tuple[int, int, list[str]]:
    """Insert rows; return (imported, skipped, errors)."""
    imported = skipped = 0
    errors = list(parse_result.errors)

    for row in parse_result.rows:
        try:
            instrument_id = _get_or_create_instrument(conn, row.isin_or_name, "EUR")
            if row.row_type == TRANSACTION_TYPE:
                if row.quantity is None or row.price is None:
                    errors.append(
                        f"Transaction row for '{row.isin_or_name}' missing quantity/price"
                    )
                    continue
                value_eur = row.amount_eur or -(row.quantity * row.price)
                try:
                    conn.execute(
                        """INSERT INTO transactions
                           (account_id, instrument_id, ts, quantity, price,
                            local_currency, value_eur, fees_eur, source)
                           VALUES (?,?,?,?,?,'EUR',?,0,'manual')""",
                        (
                            account_id,
                            instrument_id,
                            f"{row.date}T00:00:00",
                            str(row.quantity),
                            str(row.price),
                            str(value_eur),
                        ),
                    )
                    imported += 1
                except Exception as exc:
                    if "UNIQUE" in str(exc):
                        skipped += 1
                    else:
                        raise

            elif row.row_type == BALANCE_TYPE:
                try:
                    conn.execute(
                        """INSERT OR REPLACE INTO balance_snapshots
                           (account_id, date, balance_eur) VALUES (?,?,?)""",
                        (account_id, row.date, str(row.amount_eur)),
                    )
                    imported += 1
                except Exception as exc:
                    errors.append(f"Balance snapshot error: {exc}")

            elif row.row_type in GENERIC_EVENT_TYPES:
                try:
                    conn.execute(
                        """INSERT INTO cash_events
                           (account_id, instrument_id, ts, type, amount_eur,
                            description, dedup_hash)
                           VALUES (?,?,?,?,?,?,?)""",
                        (
                            account_id,
                            instrument_id,
                            f"{row.date}T00:00:00",
                            row.row_type,
                            str(row.amount_eur),
                            row.description,
                            row.dedup_hash,
                        ),
                    )
                    imported += 1
                except Exception as exc:
                    if "UNIQUE" in str(exc):
                        skipped += 1
                    else:
                        raise

            else:
                errors.append(
                    f"Unknown row type '{row.row_type}' for '{row.isin_or_name}'"
                )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Row error: {exc}")

    return imported, skipped, errors
