"""Parser for DeGiro Account.csv (Rekeningoverzicht export).

Column structure:
  Datum, Tijd, Valutadatum, Product, ISIN, Omschrijving, FX,
  Mutatie, [amount], Saldo, [amount], Order Id

The "Mutatie" column contains the CURRENCY CODE (e.g. "EUR"), and the next
unnamed column contains the AMOUNT. The same structure applies to "Saldo".

This parser handles BOTH transaction rows ("Koop 3 @ 81,92 EUR") and
cash-event rows (dividend, deposit, fee, etc.) from the same file.

Two-pass parsing:
  Pass 1 – collect FX rates from "Valuta Debitering/Creditering" rows.
  Pass 2 – classify and parse all other rows, using collected FX rates
            to convert non-EUR amounts to EUR.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
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

ACCOUNT_HEADERS = {"Omschrijving", "Valutadatum", "Saldo"}
_ENGLISH_HEADERS = {
    "Date": "Datum", "Time": "Tijd", "Value date": "Valutadatum",
    "Description": "Omschrijving", "FX rate": "FX", "Change": "Mutatie",
    "Balance": "Saldo", "Order ID": "Order Id",
}


def is_account_csv(content: str) -> bool:
    from . import strip_bom
    first_line = strip_bom(content).split("\n")[0].casefold()
    return (("omschrijving" in first_line and "valutadatum" in first_line)
            or ("description" in first_line and "value date" in first_line))


# ---------------------------------------------------------------------------
# Transaction description parser  ("Koop 3 @ 81,92 EUR")
# ---------------------------------------------------------------------------

_TXN_RE = re.compile(
    r'^(koop|verkoop|buy|sell)\s+([\d.,]+)\s*@\s*([\d.,]+)\s*([A-Z]{3})',
    re.IGNORECASE,
)

# Matches koop/verkoop anywhere in the description, e.g.:
# "SPIN-OFF: Koop 2 @ 0 EUR"  or  "DRIP: Koop 1 @ 12,50 USD"
_TXN_SEARCH_RE = re.compile(
    r'\b(koop|verkoop|buy|sell)\s+([\d.,]+)\s*@\s*([\d.,]+)\s*([A-Z]{3})',
    re.IGNORECASE,
)

# Matches: "SPLIT AANPASSING: 10 Unilever PLC @ 47,73 EUR (GB00B10RZP78)"
_SPLIT_RE = re.compile(
    r'^(?:split aanpassing|split adjustment):\s*([\d.,]+)\s+.+?@\s*([\d.,]+)\s*([A-Z]{3})',
    re.IGNORECASE,
)


def _parse_txn_description(description: str):
    """Parse 'Koop 3 @ 81,92 EUR' or 'Verkoop 5 @ 100,00 USD'.
    Also handles prefixed variants like 'SPIN-OFF: Koop 2 @ 0 EUR'.

    Returns (direction, quantity, price, price_currency) or None.
    """
    s = description.strip()
    m = _TXN_RE.match(s) or _TXN_SEARCH_RE.search(s)
    if not m:
        return None
    direction       = m.group(1).lower()
    direction = {"buy": "koop", "sell": "verkoop"}.get(direction, direction)
    quantity        = parse_dutch_decimal(m.group(2))
    price           = parse_dutch_decimal(m.group(3))
    price_currency  = m.group(4).upper()
    return direction, quantity, price, price_currency


# ---------------------------------------------------------------------------
# Classification (cash events only)
# ---------------------------------------------------------------------------

_SKIP_KEYWORDS = (
    "reservation ideal",
    "reservation sofort",
    "valuta debitering",
    "valuta creditering",
    "degiro cash sweep",
    "geldmarktfonds",
    "koersverandering geldmarktfonds",
    "compensatie geldmarktfonds",
    # Internal transfer between the DEGIRO trading ledger and the
    # flatexDEGIRO Bank cash account — always comes in matched pairs that
    # net to zero, not a real external deposit/withdrawal. The actual cash
    # balance is read from the running "Saldo" column, not from these rows.
    "geldrekening bij flatexdegiro",
)

_TYPE_KEYWORDS: list[tuple[str, str]] = [
    ("dividend tax",        "dividend_tax"),
    ("dividendbelasting",    "dividend_tax"),
    ("dividend",             "dividend"),
    ("terugstorting",        "withdrawal"),
    ("ideal storting",       "deposit"),
    ("storting",             "deposit"),
    ("deposit",              "deposit"),
    ("ideal",                "deposit"),
    ("onttrekking",          "withdrawal"),
    ("withdrawal",           "withdrawal"),
    ("aansluiting",          "fee"),
    ("transactiekosten",     "fee"),
    ("transaction fee",      "fee"),
    ("kosten",               "fee"),
    ("adr",                  "fee"),
    ("flatex interest",      "interest"),
    ("rente",                "interest"),
    ("interest",             "interest"),
    ("kapitaalsuitkering",   "other"),
    ("verrekening promotie", "other"),
]


def classify_row(description: str) -> str | None:
    """Return cash_event type, 'transaction', 'corporate_action', or None to skip."""
    d = description.lower().strip()
    # Plain buy/sell at start of description
    if d.startswith(("koop ", "verkoop ", "buy ", "sell ")):
        return "transaction"
    # Corporate actions → need manual review
    if d.startswith(("split aanpassing", "split adjustment")):
        return "corporate_action"
    # Embedded koop/verkoop (e.g. "SPIN-OFF: Koop 2 @ 0 EUR", "DRIP: Koop 1 @ ...")
    if _TXN_SEARCH_RE.search(description):
        return "transaction"
    for keyword in _SKIP_KEYWORDS:
        if keyword in d:
            return None
    for keyword, event_type in _TYPE_KEYWORDS:
        if keyword.lower() in d:
            return event_type
    return "other"


# ---------------------------------------------------------------------------
# Parsed row types
# ---------------------------------------------------------------------------

@dataclass
class AccountTxnRow:
    """A buy or sell transaction parsed from the account statement."""
    ts: str
    product: str
    isin: Optional[str]
    exchange: str
    order_id: Optional[str]
    quantity: Decimal          # positive = buy, negative = sell
    price: Decimal
    price_currency: str
    local_currency: str
    fx_rate: Optional[Decimal]
    value_eur: Decimal         # absolute value in EUR (positive)
    fees_eur: Decimal          # folded in from the matching fee row via Order Id (0 if none)
    dedup_hash: str


@dataclass
class AccountRow:
    ts: str
    product: str
    isin: Optional[str]
    description: str
    event_type: str
    amount_raw: Decimal
    amount_currency: str
    amount_eur: Decimal
    fx_rate: Optional[Decimal]
    order_id: Optional[str]
    dedup_hash: str


@dataclass
class CorporateActionRow:
    """A corporate action row (split, merger, etc.) that needs manual review."""
    ts: str
    product: str
    isin: Optional[str]
    description: str
    quantity: Decimal
    price: Decimal
    price_currency: str
    dedup_hash: str


@dataclass
class AccountParseResult:
    txn_rows: list[AccountTxnRow] = field(default_factory=list)
    rows: list[AccountRow] = field(default_factory=list)
    corporate_actions: list[CorporateActionRow] = field(default_factory=list)
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    # Uninvested cash still sitting on the account, derived from the running
    # "Saldo" column — last known balance per currency (raw), plus a EUR
    # total using the historical in-file FX rate as a network-free fallback.
    # Callers should prefer converting cash_balances_raw with a live FX rate
    # and only fall back to cash_balance_eur when that's unavailable.
    cash_balances_raw: dict[str, Decimal] = field(default_factory=dict)
    cash_balance_eur: Optional[Decimal] = None
    cash_balance_date: Optional[str] = None


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse(content: str) -> AccountParseResult:
    lines = content.splitlines()
    if lines:
        for source, target in _ENGLISH_HEADERS.items():
            lines[0] = lines[0].replace(source, target)
        content = "\n".join(lines)
    col, data_rows = read_csv_rows(content)
    result = AccountParseResult()

    # Pass 1 – collect FX rates keyed by (date, non-EUR currency)
    fx_by_date: dict[tuple[str, str], Decimal] = {}
    for raw in data_rows:
        desc = col.get(raw, "Omschrijving").lower()
        if "valuta" in desc and ("debitering" in desc or "creditering" in desc):
            fx_str = col.get(raw, "FX")
            if fx_str:
                ccy = col.get(raw, "Mutatie")
                date_str = parse_dutch_date(col.get(raw, "Datum"))
                if ccy and ccy != "EUR" and date_str:
                    try:
                        fx_by_date[(date_str, ccy)] = parse_dutch_decimal(fx_str)
                    except Exception:
                        pass

    # Pass 1b – collect per-trade fees keyed by Order Id, so they can be
    # folded into the trade's own fees_eur (DeGiro reports a trade's
    # commission as a separate row sharing the same Order Id — without this,
    # transaction costs would never reduce cost basis / realized P/L, only
    # ever appear as a standalone cash event). Account-level fees with no
    # Order Id (e.g. annual connection fee) are deliberately left out — they
    # aren't tied to acquiring/disposing of a specific position.
    fee_by_order: dict[str, Decimal] = {}
    for raw in data_rows:
        if classify_row(col.get(raw, "Omschrijving")) != "fee":
            continue
        order_id = col.get(raw, "Order Id") or col.get(raw, "Order ID")
        if not order_id:
            continue
        amount_currency = col.get(raw, "Mutatie") or "EUR"
        amount_str = col.get_next(raw, "Mutatie")
        if not amount_str:
            continue
        amount_raw = parse_dutch_decimal(amount_str)
        if amount_currency != "EUR":
            date_str = parse_dutch_date(col.get(raw, "Datum"))
            fx_rate = fx_by_date.get((date_str, amount_currency))
            amount_raw = (amount_raw / fx_rate) if fx_rate else amount_raw
        fee_by_order[order_id] = fee_by_order.get(order_id, Decimal("0")) + amount_raw

    # Track the running "Saldo" (balance) per currency so we can report the
    # uninvested cash still sitting on the account — every row carries a
    # currency + running balance, whatever its classification.
    latest_balance: dict[str, tuple[str, Decimal]] = {}  # ccy -> (ts, balance)

    # Pass 2 – parse rows
    for raw in data_rows:
        try:
            datum = col.get(raw, "Datum")
            if datum:
                datum_iso = parse_dutch_date(datum)
                tijd = col.get(raw, "Tijd")
                ts = f"{datum_iso}T{tijd}:00" if tijd else f"{datum_iso}T00:00:00"
                saldo_ccy = col.get(raw, "Saldo")
                saldo_str = col.get_next(raw, "Saldo")
                # Sanity-check: a malformed row (e.g. an unquoted comma inside
                # another field shifting columns) must never poison the cash
                # balance with a bogus "currency".
                if saldo_ccy and saldo_str and re.fullmatch(r"[A-Za-z]{3}", saldo_ccy):
                    saldo_val = parse_dutch_decimal(saldo_str)
                    prev = latest_balance.get(saldo_ccy)
                    if prev is None or ts >= prev[0]:
                        latest_balance[saldo_ccy] = (ts, saldo_val)

            row_type = classify_row(col.get(raw, "Omschrijving"))
            if row_type is None:
                result.skipped += 1
            elif row_type == "transaction":
                txn = _parse_txn_row(col, raw, fx_by_date, fee_by_order)
                if txn:
                    result.txn_rows.append(txn)
                else:
                    result.skipped += 1
            elif row_type == "corporate_action":
                ca = _parse_corporate_action_row(col, raw)
                if ca:
                    result.corporate_actions.append(ca)
                else:
                    result.skipped += 1
            else:
                arow = _parse_event_row(col, raw, fx_by_date, row_type)
                if arow:
                    result.rows.append(arow)
                else:
                    result.skipped += 1
        except Exception as exc:
            result.errors.append(f"Row {raw!r}: {exc}")

    if latest_balance:
        result.cash_balances_raw = {ccy: amount for ccy, (ts, amount) in latest_balance.items()}

        # Most recent conversion rate seen per non-EUR currency (same
        # native-units-per-EUR convention as the transaction/event parsers).
        latest_fx: dict[str, tuple[str, Decimal]] = {}
        for (dt, ccy), rate in fx_by_date.items():
            prev = latest_fx.get(ccy)
            if prev is None or dt >= prev[0]:
                latest_fx[ccy] = (dt, rate)

        total_eur = Decimal("0")
        latest_date = None
        for ccy, (ts, amount) in latest_balance.items():
            if ccy == "EUR":
                eur_amount = amount
            else:
                fx = latest_fx.get(ccy)
                eur_amount = (amount / fx[1]) if fx and fx[1] else amount
            total_eur += eur_amount
            row_date = ts[:10]
            if latest_date is None or row_date > latest_date:
                latest_date = row_date

        result.cash_balance_eur = total_eur.quantize(Decimal("0.01"), ROUND_HALF_UP)
        result.cash_balance_date = latest_date

    return result


def _parse_txn_row(
    col: ColumnIndex,
    raw: list[str],
    fx_by_date: dict[tuple[str, str], Decimal],
    fee_by_order: dict[str, Decimal] | None = None,
) -> Optional[AccountTxnRow]:
    datum = col.get(raw, "Datum")
    if not datum:
        return None

    description = col.get(raw, "Omschrijving")
    parsed = _parse_txn_description(description)
    if not parsed:
        return None
    direction, quantity, price, price_currency = parsed

    datum_iso = parse_dutch_date(datum)
    tijd = col.get(raw, "Tijd")
    ts = f"{datum_iso}T{tijd}:00" if tijd else f"{datum_iso}T00:00:00"

    # Mutatie = total value (currency + amount)
    amount_currency = col.get(raw, "Mutatie") or "EUR"
    amount_str = col.get_next(raw, "Mutatie")
    amount_raw = parse_dutch_decimal(amount_str) if amount_str else Decimal("0")

    fx_str = col.get(raw, "FX")
    fx_rate: Optional[Decimal] = parse_dutch_decimal(fx_str) if fx_str else None
    if fx_rate is None:
        fx_rate = fx_by_date.get((datum_iso, amount_currency))

    if amount_currency == "EUR":
        value_eur = amount_raw  # negative for buys (money out), positive for sells
    elif fx_rate and fx_rate != 0:
        value_eur = (amount_raw / fx_rate).quantize(Decimal("0.0001"))
    else:
        value_eur = amount_raw

    # Sells have negative quantity
    if direction == "verkoop":
        quantity = -quantity

    isin     = col.get(raw, "ISIN") or None
    product  = col.get(raw, "Product") or ""
    order_id = col.get(raw, "Order Id") or col.get(raw, "Order ID") or None

    fees_eur = (fee_by_order or {}).get(order_id, Decimal("0")) if order_id else Decimal("0")

    return AccountTxnRow(
        ts=ts,
        product=product,
        isin=isin,
        exchange="",
        order_id=order_id,
        quantity=quantity,
        price=price,
        price_currency=price_currency,
        local_currency=price_currency,
        fx_rate=fx_rate,
        value_eur=value_eur,
        fees_eur=fees_eur,
        dedup_hash=row_hash(raw),
    )


def _parse_corporate_action_row(
    col: ColumnIndex,
    raw: list[str],
) -> Optional[CorporateActionRow]:
    """Parse a SPLIT AANPASSING row into a CorporateActionRow."""
    datum = col.get(raw, "Datum")
    if not datum:
        return None

    description = col.get(raw, "Omschrijving")
    m = _SPLIT_RE.match(description.strip())
    if not m:
        return None

    quantity       = parse_dutch_decimal(m.group(1))
    price          = parse_dutch_decimal(m.group(2))
    price_currency = m.group(3).upper()

    datum_iso = parse_dutch_date(datum)
    tijd = col.get(raw, "Tijd")
    ts = f"{datum_iso}T{tijd}:00" if tijd else f"{datum_iso}T00:00:00"

    isin    = col.get(raw, "ISIN") or None
    product = col.get(raw, "Product") or ""

    return CorporateActionRow(
        ts=ts,
        product=product,
        isin=isin,
        description=description,
        quantity=quantity,
        price=price,
        price_currency=price_currency,
        dedup_hash=row_hash(raw),
    )


def _parse_event_row(
    col: ColumnIndex,
    raw: list[str],
    fx_by_date: dict[tuple[str, str], Decimal],
    event_type: str,
) -> Optional[AccountRow]:
    datum = col.get(raw, "Datum")
    if not datum:
        return None

    datum_iso = parse_dutch_date(datum)
    tijd = col.get(raw, "Tijd")
    ts = f"{datum_iso}T{tijd}:00" if tijd else f"{datum_iso}T00:00:00"

    amount_currency = col.get(raw, "Mutatie") or "EUR"
    amount_str = col.get_next(raw, "Mutatie")
    amount_raw = parse_dutch_decimal(amount_str) if amount_str else Decimal("0")

    fx_str = col.get(raw, "FX")
    fx_rate: Optional[Decimal] = parse_dutch_decimal(fx_str) if fx_str else None
    if fx_rate is None:
        fx_rate = fx_by_date.get((datum_iso, amount_currency))

    if amount_currency == "EUR":
        amount_eur = amount_raw
    elif fx_rate and fx_rate != 0:
        amount_eur = (amount_raw / fx_rate).quantize(Decimal("0.0001"))
    else:
        amount_eur = amount_raw

    isin     = col.get(raw, "ISIN") or None
    product  = col.get(raw, "Product")
    order_id = col.get(raw, "Order Id") or col.get(raw, "Order ID") or None
    description = col.get(raw, "Omschrijving")

    return AccountRow(
        ts=ts,
        product=product,
        isin=isin,
        description=description,
        event_type=event_type,
        amount_raw=amount_raw,
        amount_currency=amount_currency,
        amount_eur=amount_eur,
        fx_rate=fx_rate,
        order_id=order_id,
        dedup_hash=row_hash(raw),
    )


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _get_instrument_id(conn: sqlite3.Connection, isin: str | None,
                        name: str) -> int | None:
    if not isin:
        return None
    row = conn.execute(
        "SELECT id FROM instruments WHERE isin=?", (isin,)
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO instruments(isin, name) VALUES (?,?)", (isin, name)
    )
    return cur.lastrowid  # type: ignore[return-value]


def commit_account_events(
    conn: sqlite3.Connection, result: AccountParseResult, account_id: int,
) -> tuple[int, int, list[str]]:
    """Commit a parsed Account.csv result without the UI staging step.

    The web flow deliberately stages imports for preview first.  This small
    helper keeps the parser independently usable and makes idempotency
    testable: both transaction and cash-event rows use their raw-row hash.
    """
    imported = skipped = 0
    errors: list[str] = []

    for txn in result.txn_rows:
        try:
            instrument_id = _get_instrument_id(conn, txn.isin, txn.product)
            if instrument_id is None:
                raise ValueError("transaction has no ISIN")
            cur = conn.execute(
                """INSERT OR IGNORE INTO transactions
                   (account_id, instrument_id, ts, quantity, price, local_currency,
                    fx_rate, value_eur, fees_eur, order_id, source, dedup_hash)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (account_id, instrument_id, txn.ts, str(txn.quantity), str(txn.price),
                 txn.local_currency, str(txn.fx_rate) if txn.fx_rate else None,
                 str(txn.value_eur), str(txn.fees_eur), txn.order_id,
                 "degiro_account_csv", txn.dedup_hash),
            )
            if cur.rowcount:
                imported += 1
            else:
                skipped += 1
        except Exception as exc:
            errors.append(f"transaction {txn.ts}: {exc}")

    for row in result.rows:
        try:
            instrument_id = _get_instrument_id(conn, row.isin, row.product)
            cur = conn.execute(
                """INSERT OR IGNORE INTO cash_events
                   (account_id, instrument_id, ts, type, amount_eur, description, dedup_hash)
                   VALUES (?,?,?,?,?,?,?)""",
                (account_id, instrument_id, row.ts, row.event_type, str(row.amount_eur),
                 row.description, row.dedup_hash),
            )
            if cur.rowcount:
                imported += 1
            else:
                skipped += 1
        except Exception as exc:
            errors.append(f"cash event {row.ts}: {exc}")

    return imported, skipped, errors
