"""Shared CSV parsing utilities used by all importer modules."""
from __future__ import annotations

import csv
import hashlib
from decimal import Decimal, InvalidOperation
from io import StringIO
from typing import Iterator


def strip_bom(text: str) -> str:
    """Remove UTF-8 BOM if present."""
    return text.lstrip("\ufeff")


def parse_dutch_decimal(s: str) -> Decimal:
    """Parse Dutch-formatted decimal string (e.g. '1.234,56' or '-500,00')."""
    s = s.strip().strip('"').replace(" ", "")
    if not s or s == "-":
        return Decimal("0")
    # Remove thousands separator (period), replace decimal comma with period
    s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return Decimal("0")


def parse_decimal(s: str) -> Decimal:
    """Parse a decimal that may be Dutch ('1.234,56') or US/ISO ('1234.56')."""
    s = s.strip().strip('"').replace(" ", "")
    if not s or s == "-":
        return Decimal("0")
    if "," in s:
        return parse_dutch_decimal(s)
    try:
        return Decimal(s)
    except InvalidOperation:
        return Decimal("0")


def row_hash(raw_row: list[str]) -> str:
    """SHA-256 of the raw CSV row string (used as dedup_hash for cash events)."""
    raw = ",".join(raw_row)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_dutch_date(s: str) -> str:
    """Convert 'dd-mm-yyyy' to ISO 'yyyy-mm-dd'.  Passes through ISO dates."""
    s = s.strip()
    if not s:
        return ""
    parts = s.split("-")
    if len(parts) == 3 and len(parts[0]) == 2:
        # dd-mm-yyyy → yyyy-mm-dd
        return f"{parts[2]}-{parts[1]}-{parts[0]}"
    return s  # already ISO or unknown format


class ColumnIndex:
    """Helper that maps header names → column indices and provides safe accessors."""

    def __init__(self, headers: list[str]) -> None:
        self._headers = headers
        self._named: dict[str, int] = {}
        for i, h in enumerate(headers):
            name = h.strip()
            if name:
                self._named[name] = i

    def idx(self, name: str) -> int | None:
        return self._named.get(name)

    def get(self, row: list[str], name: str, default: str = "") -> str:
        i = self._named.get(name)
        if i is None or i >= len(row):
            return default
        return row[i].strip().strip('"')

    def get_at(self, row: list[str], index: int, default: str = "") -> str:
        if index < 0 or index >= len(row):
            return default
        return row[index].strip().strip('"')

    def get_next(self, row: list[str], name: str, default: str = "") -> str:
        """Value in the unnamed column immediately after the named column."""
        i = self._named.get(name)
        if i is None:
            return default
        return self.get_at(row, i + 1, default)

    @property
    def names(self) -> list[str]:
        return list(self._named.keys())


def read_csv_rows(content: str) -> tuple[ColumnIndex, list[list[str]]]:
    """Read CSV text → (ColumnIndex, list of data rows).

    DEGIRO chooses the separator from the account locale: Dutch exports are
    commonly comma-separated, but some accounts receive a semicolon-separated
    file. Detect it from the header rather than treating the entire file as
    one column. The same behaviour is useful for generic CSV imports.
    """
    content = strip_bom(content)
    header_line = next((line for line in content.splitlines() if line.strip()), "")
    delimiter = max((",", ";", "\t"), key=header_line.count)
    reader = csv.reader(StringIO(content), delimiter=delimiter)
    rows: list[list[str]] = list(reader)
    if not rows:
        return ColumnIndex([]), []
    header_row = rows[0]
    col = ColumnIndex(header_row)
    data_rows = [r for r in rows[1:] if any(v.strip() for v in r)]
    return col, data_rows


def iter_csv_rows(content: str) -> Iterator[tuple[ColumnIndex, list[str]]]:
    """Yield (ColumnIndex, row) for each data row."""
    col, data_rows = read_csv_rows(content)
    for row in data_rows:
        yield col, row
