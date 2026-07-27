"""Regression tests for migrations that transform existing portfolio data."""
from __future__ import annotations

import sqlite3
from pathlib import Path


MIGRATIONS = Path(__file__).parent.parent / "migrations"


def test_trading_line_migration_splits_existing_isin_by_currency(tmp_path):
    conn = sqlite3.connect(tmp_path / "portfolio.db")
    conn.row_factory = sqlite3.Row
    for migration in sorted(MIGRATIONS.glob("0[0-1][0-9]_*.sql")):
        conn.executescript(migration.read_text(encoding="utf-8"))

    conn.execute("INSERT INTO accounts(id,name,type,currency) VALUES(1,'Broker','broker','EUR')")
    conn.execute(
        "INSERT INTO instruments(id,isin,name,symbol,currency) "
        "VALUES(1,'IE00TEST0001','Example ETF','EXAMPLE.AS','EUR')"
    )
    conn.executemany(
        """INSERT INTO transactions(account_id,instrument_id,ts,quantity,price,local_currency,value_eur,fees_eur,source)
           VALUES(1,1,?,?,?,?,?,?, 'test')""",
        [
            ("2025-01-01T10:00:00", "1", "100", "EUR", "-100", "0"),
            ("2025-01-02T10:00:00", "1", "100", "USD", "-90", "0"),
        ],
    )
    conn.commit()

    conn.executescript((MIGRATIONS / "011_instrument_trading_lines.sql").read_text(encoding="utf-8"))

    lines = conn.execute(
        "SELECT id, trading_currency, symbol FROM instruments WHERE isin='IE00TEST0001' ORDER BY trading_currency"
    ).fetchall()
    assert [(line["trading_currency"], line["symbol"]) for line in lines] == [
        ("EUR", "EXAMPLE.AS"),
        ("USD", None),
    ]
    transactions = conn.execute(
        "SELECT instrument_id, local_currency FROM transactions ORDER BY ts"
    ).fetchall()
    assert transactions[0]["instrument_id"] != transactions[1]["instrument_id"]
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_promotion_migration_reclassifies_existing_cash_event(tmp_path):
    conn = sqlite3.connect(tmp_path / "portfolio.db")
    conn.executescript((MIGRATIONS / "001_init.sql").read_text(encoding="utf-8"))
    conn.execute("INSERT INTO accounts(id,name,type,currency) VALUES(1,'Broker','broker','EUR')")
    conn.execute(
        """INSERT INTO cash_events(account_id,ts,type,amount_eur,description)
           VALUES(1,'2023-01-13T00:00:00','other','4.90','DEGIRO Verrekening Promotie')"""
    )

    conn.executescript((MIGRATIONS / "012_promotion_bonus.sql").read_text(encoding="utf-8"))

    assert conn.execute("SELECT type FROM cash_events").fetchone()[0] == "bonus"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
