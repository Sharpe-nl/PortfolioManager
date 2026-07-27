"""Tests for XIRR and benchmark calculations."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

from app.services.benchmark import get_benchmark_comparison, xirr


class TestXIRR:
    def test_simple_return(self):
        """Invest 1000, get back 1100 exactly one year later → 10%."""
        cf = [("2024-01-01", Decimal("-1000")), ("2025-01-01", Decimal("1100"))]
        r = xirr(cf)
        assert r is not None
        assert abs(r - 0.10) < 0.001

    def test_negative_return(self):
        cf = [("2024-01-01", Decimal("-1000")), ("2025-01-01", Decimal("900"))]
        r = xirr(cf)
        assert r is not None
        assert r < 0

    def test_zero_return(self):
        cf = [("2024-01-01", Decimal("-1000")), ("2025-01-01", Decimal("1000"))]
        r = xirr(cf)
        assert r is not None
        assert abs(r) < 0.001

    def test_multiple_cash_flows(self):
        """Two deposits of 500 each, final value 1200 after ~1 year."""
        cf = [
            ("2024-01-01", Decimal("-500")),
            ("2024-07-01", Decimal("-500")),
            ("2025-01-01", Decimal("1200")),
        ]
        r = xirr(cf)
        assert r is not None
        assert r > 0

    def test_empty_returns_none(self):
        assert xirr([]) is None

    def test_single_flow_returns_none_or_zero(self):
        """Single cash flow has no meaningful XIRR."""
        r = xirr([("2024-01-01", Decimal("-1000"))])
        # May or may not converge; we just don't crash
        # If it returns something, it should not be a crazy number
        if r is not None:
            assert abs(r) < 100


class TestBenchmarkSeries:
    def test_savings_cash_flows_are_excluded(self, mem_db):
        """The stock benchmark must never receive savings-account deposits."""
        mem_db.execute("INSERT INTO accounts(id,name,type,currency) VALUES(2,'Savings','savings','EUR')")
        mem_db.execute(
            "INSERT INTO cash_events(account_id,ts,type,amount_eur) VALUES(2,'2025-01-01T00:00:00','deposit','20000')"
        )
        mem_db.commit()

        import app.services.benchmark as bm
        first_date, cash_flows, portfolio_series = bm.get_deposits_and_portfolio_series(mem_db)

        assert first_date is None
        assert cash_flows == []
        assert portfolio_series == []

    def test_later_deposit_not_counted_before_it_happened(self, mem_db):
        """A second deposit must not inflate the benchmark's value at dates
        before it was actually made — regression test for a bug where the
        FINAL total of benchmark shares (from all deposits) was applied to
        every point in the series, including points before later deposits
        happened."""
        mem_db.execute(
            "INSERT INTO instruments(id,isin,name,symbol,asset_type) "
            "VALUES (1,'IE00X','HELD','HELD.AS','etf')"
        )
        mem_db.execute(
            "INSERT INTO cash_events(account_id,ts,type,amount_eur) "
            "VALUES (1,'2025-01-01T00:00:00','deposit',1000.00)"
        )
        mem_db.execute(
            "INSERT INTO cash_events(account_id,ts,type,amount_eur) "
            "VALUES (1,'2025-04-01T00:00:00','deposit',1000.00)"
        )
        mem_db.execute(
            """INSERT INTO transactions
               (account_id,instrument_id,ts,quantity,price,local_currency,value_eur,fees_eur,source)
               VALUES (1,1,'2025-01-01T10:00:00',5,100,'EUR',-500,0,'manual')"""
        )
        for d in ["2025-01-01", "2025-02-01", "2025-04-01"]:
            mem_db.execute(
                "INSERT INTO prices(instrument_id,date,close,currency,fetched_at) "
                "VALUES (1,?,?,?,datetime('now'))", (d, "100.00", "EUR"),
            )
        mem_db.execute(
            "INSERT INTO instruments(id,isin,name,symbol,asset_type) "
            "VALUES (2,NULL,'VWRL.AS','VWRL.AS','etf')"
        )
        for d in ["2025-01-01", "2025-02-01", "2025-04-01"]:
            mem_db.execute(
                "INSERT INTO prices(instrument_id,date,close,currency,fetched_at) "
                "VALUES (2,?,?,?,datetime('now'))", (d, "50.00", "EUR"),
            )
        mem_db.commit()

        import app.services.benchmark as bm
        with patch.object(bm, "_get_benchmark_id", return_value=2), \
             patch.object(bm, "refresh_history", return_value=None):
            result = get_benchmark_comparison(mem_db, "VWRL.AS", account_id=1)

        by_date = {pt["date"]: pt["value"] for pt in result["benchmark_series"]}
        # Before the second deposit: only the first 1000/50 = 20 shares -> 1000.00
        assert by_date["2025-01-01"] == Decimal("1000.00")
        assert by_date["2025-02-01"] == Decimal("1000.00")
        # From the second deposit onward: 40 shares -> 2000.00
        assert by_date["2025-04-01"] == Decimal("2000.00")

    def test_withdrawal_sells_benchmark_shares(self, mem_db):
        """An external withdrawal must reduce the hypothetical benchmark,
        rather than leaving the original deposit invested indefinitely."""
        mem_db.execute(
            "INSERT INTO instruments(id,isin,name,symbol,asset_type) "
            "VALUES (1,'IE00X','HELD','HELD.AS','etf')"
        )
        mem_db.executemany(
            "INSERT INTO cash_events(account_id,ts,type,amount_eur) VALUES(1,?,?,?)",
            [
                ("2025-01-01T00:00:00", "deposit", "1000"),
                ("2025-02-01T00:00:00", "withdrawal", "-500"),
            ],
        )
        mem_db.execute(
            """INSERT INTO transactions
               (account_id,instrument_id,ts,quantity,price,local_currency,value_eur,fees_eur,source)
               VALUES(1,1,'2025-01-01T10:00:00',5,100,'EUR',-500,0,'manual')"""
        )
        for d in ["2025-01-01", "2025-02-01"]:
            mem_db.execute(
                "INSERT INTO prices(instrument_id,date,close,currency,fetched_at) "
                "VALUES(1,?,?,?,datetime('now'))", (d, "100", "EUR"),
            )
        mem_db.execute(
            "INSERT INTO instruments(id,name,symbol,asset_type) VALUES(2,'Benchmark: VWRL.AS','VWRL.AS','etf')"
        )
        for d, price in [("2025-01-01", "50"), ("2025-02-01", "55")]:
            mem_db.execute(
                "INSERT INTO prices(instrument_id,date,close,currency,fetched_at) "
                "VALUES(2,?,?,?,datetime('now'))", (d, price, "EUR"),
            )
        mem_db.commit()

        import app.services.benchmark as bm
        with patch.object(bm, "_get_benchmark_id", return_value=2), \
             patch.object(bm, "refresh_history", return_value=None):
            result = get_benchmark_comparison(mem_db, "VWRL.AS", account_id=1)

        by_date = {pt["date"]: pt["value"] for pt in result["benchmark_series"]}
        # 20 shares bought at €50; withdrawing €500 at €55 sells 9.0909…
        # shares, leaving €600 at the €55 close — not €1,100.
        assert by_date["2025-02-01"] == Decimal("600.00")
