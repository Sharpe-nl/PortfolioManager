"""Domain dataclasses.  No ORM — just plain data containers."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional


@dataclass
class Account:
    id: int
    name: str
    type: str          # 'broker' | 'pension' | 'savings' | 'other'
    currency: str = "EUR"


@dataclass
class Instrument:
    id: int
    name: str
    isin: Optional[str] = None
    symbol: Optional[str] = None
    exchange: Optional[str] = None
    currency: Optional[str] = None
    trading_currency: Optional[str] = None
    asset_type: str = "other"
    sector: Optional[str] = None
    region: Optional[str] = None


@dataclass
class Transaction:
    id: int
    account_id: int
    instrument_id: int
    ts: str                      # ISO 8601
    quantity: Decimal
    price: Decimal
    local_currency: str
    value_eur: Decimal
    fees_eur: Decimal = field(default_factory=lambda: Decimal("0"))
    fx_rate: Optional[Decimal] = None
    order_id: Optional[str] = None
    source: str = "manual"


@dataclass
class CashEvent:
    id: int
    account_id: int
    ts: str
    type: str                    # 'dividend' | 'dividend_tax' | 'fee' | …
    amount_eur: Decimal
    instrument_id: Optional[int] = None
    description: Optional[str] = None
    dedup_hash: Optional[str] = None


@dataclass
class PriceRecord:
    instrument_id: int
    date: str
    close: Decimal
    currency: str
    fetched_at: str


@dataclass
class Holding:
    instrument: Instrument
    account_id: int
    account_name: str
    quantity: Decimal
    avg_cost: Decimal
    cost_basis: Decimal
    current_price: Optional[Decimal] = None
    current_value: Optional[Decimal] = None
    unrealized_pl: Optional[Decimal] = None
    unrealized_pl_pct: Optional[Decimal] = None
    weight: Optional[Decimal] = None


@dataclass
class ImportPreviewRow:
    row_type: str          # 'transaction' | 'cash_event' | 'skip'
    status: str            # 'new' | 'duplicate' | 'error' | 'informational'
    description: str       # human-readable summary for the preview table
    error_msg: Optional[str] = None


@dataclass
class ImportResult:
    """Summary returned after a confirmed import."""
    filename: str
    file_type: str
    rows_imported: int = 0
    rows_skipped: int = 0
    rows_error: int = 0
    errors: list[str] = field(default_factory=list)
