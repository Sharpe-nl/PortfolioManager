"""Shared pytest fixtures."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture()
def transactions_csv() -> str:
    return (FIXTURES_DIR / "transactions.csv").read_text(encoding="utf-8")


@pytest.fixture()
def account_csv() -> str:
    return (FIXTURES_DIR / "account.csv").read_text(encoding="utf-8")


@pytest.fixture()
def mem_db() -> sqlite3.Connection:
    """In-memory SQLite database with the full schema applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    migrations_dir = Path(__file__).parent.parent / "migrations"
    for sql_file in sorted(migrations_dir.glob("*.sql")):
        conn.executescript(sql_file.read_text(encoding="utf-8"))
    conn.execute("INSERT INTO accounts(id,name,type,currency) VALUES (1,'DeGiro','broker','EUR')")
    conn.commit()
    return conn
