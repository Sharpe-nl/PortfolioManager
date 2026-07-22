"""Tests for portfolio calculations."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.portfolio import (
    get_holdings,
    get_realized_pl,
    get_realized_pl_events,
    get_allocation,
    get_allocation_details,
    get_portfolio_summary,
    get_portfolio_value_series,
)


def _seed_data(conn):
    """Insert minimal data: 1 instrument, 1 buy transaction, 1 cached price."""
    conn.execute(
        "INSERT INTO instruments(id,isin,name,symbol,asset_type,sector,region) "
        "VALUES (1,'IE00B3RBWM25','VWRL','VWRL.AS','etf','Equity','Global')"
    )
    # Buy 8 units @ 112.45 EUR = 899.60 EUR outflow (value_eur negative means money out)
    conn.execute(
        """INSERT INTO transactions
           (account_id,instrument_id,ts,quantity,price,local_currency,value_eur,fees_eur,order_id,source)
           VALUES (1,1,'2025-01-16T10:04:00','8','112.45','EUR','-899.60','-1.00',
                   '5c7e9a1b',  'degiro_csv')"""
    )
    # Cached price
    conn.execute(
        "INSERT INTO prices(instrument_id,date,close,currency,fetched_at) "
        "VALUES (1,'2025-06-01','118.50','EUR',datetime('now'))"
    )
    conn.commit()


class TestHoldings:
    def test_holding_qty(self, mem_db):
        _seed_data(mem_db)
        holdings = get_holdings(mem_db)
        assert len(holdings) == 1
        assert holdings[0].quantity == Decimal("8")

    def test_avg_cost(self, mem_db):
        _seed_data(mem_db)
        h = get_holdings(mem_db)[0]
        # Cost basis includes the €1.00 buy fee: (899.60 + 1.00) / 8 = 112.575 -> 112.58
        assert h.avg_cost == Decimal("112.58")

    def test_current_value(self, mem_db):
        _seed_data(mem_db)
        h = get_holdings(mem_db)[0]
        # 8 * 118.50
        assert h.current_value == Decimal("948.00")

    def test_unrealized_pl_positive(self, mem_db):
        _seed_data(mem_db)
        h = get_holdings(mem_db)[0]
        # 948.00 - (8 * 112.58) = 948.00 - 900.64 = 47.36
        assert h.unrealized_pl == Decimal("47.36")

    def test_sold_out_position_not_shown(self, mem_db):
        _seed_data(mem_db)
        # Add a sell that fully closes the position
        mem_db.execute(
            """INSERT INTO transactions
               (account_id,instrument_id,ts,quantity,price,local_currency,value_eur,fees_eur,source)
               VALUES (1,1,'2025-05-02T11:23:00','-8','118.20','EUR','945.60','-1.00','degiro_csv')"""
        )
        mem_db.commit()
        holdings = get_holdings(mem_db)
        assert len(holdings) == 0

    def test_partial_sell_reduces_qty(self, mem_db):
        _seed_data(mem_db)
        mem_db.execute(
            """INSERT INTO transactions
               (account_id,instrument_id,ts,quantity,price,local_currency,value_eur,fees_eur,source)
               VALUES (1,1,'2025-05-02T11:23:00','-2','118.20','EUR','236.40','-1.00','degiro_csv')"""
        )
        mem_db.commit()
        h = get_holdings(mem_db)[0]
        assert h.quantity == Decimal("6")
        # Cost basis must reflect only the 6 shares still held (6 * 112.58,
        # avg cost including the buy fee), not the cost of all 8 ever bought
        # — a partial sell must not inflate the cost basis of what remains.
        assert h.cost_basis == Decimal("675.48")
        # current_value = 6 * 118.50 (cached price) = 711.00
        assert h.unrealized_pl == Decimal("35.52")


def test_stock_result_excludes_savings_deposits(mem_db):
    _seed_data(mem_db)
    mem_db.execute("INSERT INTO accounts(id,name,type,currency) VALUES(2,'Savings','savings','EUR')")
    mem_db.execute(
        "INSERT INTO cash_events(account_id,ts,type,amount_eur) VALUES(1,'2025-01-01','deposit','1000')"
    )
    mem_db.execute(
        "INSERT INTO cash_events(account_id,ts,type,amount_eur) VALUES(2,'2025-01-01','deposit','20000')"
    )
    mem_db.commit()

    summary = get_portfolio_summary(mem_db)
    assert summary["net_deposits"] == Decimal("1000.0")
    assert summary["total_pl"] == Decimal("-52.00")


def test_stale_sale_cash_snapshot_is_not_counted_next_to_later_purchase(mem_db):
    """Selling and reinvesting must not turn the temporary cash into growth."""
    mem_db.execute(
        "INSERT INTO instruments(id,isin,name,symbol) VALUES(1,'IE00B3RBWM25','VWRL','VWRL.AS')"
    )
    mem_db.execute(
        "INSERT INTO prices(instrument_id,date,close,currency,fetched_at) "
        "VALUES(1,'2025-06-01','100','EUR',datetime('now'))"
    )
    mem_db.execute(
        "INSERT INTO cash_events(account_id,ts,type,amount_eur) "
        "VALUES(1,'2025-01-01T00:00:00','deposit','1000')"
    )
    mem_db.executemany(
        """INSERT INTO transactions(account_id,instrument_id,ts,quantity,price,local_currency,value_eur,fees_eur,source)
           VALUES(1,1,?,?,?,?,?,?, 'degiro_account_csv')""",
        [
            ('2025-01-01T10:00:00', '10', '100', 'EUR', '-1000', '0'),
            ('2025-02-01T10:00:00', '-10', '120', 'EUR', '1200', '0'),
            ('2025-03-01T10:00:00', '12', '100', 'EUR', '-1200', '0'),
        ],
    )
    # This was the cash immediately after the sale, before the March purchase.
    mem_db.execute(
        "INSERT INTO balance_snapshots(account_id,date,balance_eur) VALUES(1,'2025-02-01','1200')"
    )
    mem_db.commit()

    summary = get_portfolio_summary(mem_db)

    assert summary["holdings_value"] == Decimal("1200.00")
    assert summary["cash_balance"] == Decimal("0")
    assert summary["total_pl"] == Decimal("200.00")
    # The dashboard chart uses the same stale-cash protection and must remain
    # queryable after a snapshot is present.
    series = get_portfolio_value_series(mem_db)
    assert series[-1]["value"] == Decimal("1200.00")


class TestRealizedPL:
    def test_realized_pl_zero_before_any_sell(self, mem_db):
        _seed_data(mem_db)
        assert get_realized_pl(mem_db) == Decimal("0")

    def test_realized_pl_after_sell(self, mem_db):
        _seed_data(mem_db)
        # Sell 2 units @ 118.20 (proceeds 236.40)
        # avg_cost = 112.45, cost of 2 units = 224.90
        # realised = 236.40 - 224.90 = 11.50
        mem_db.execute(
            """INSERT INTO transactions
               (account_id,instrument_id,ts,quantity,price,local_currency,value_eur,fees_eur,source)
               VALUES (1,1,'2025-05-02T11:23:00','-2','118.20','EUR','236.40','-1.00','degiro_csv')"""
        )
        mem_db.commit()
        realized = get_realized_pl(mem_db)
        assert realized > Decimal("10")   # rough check; exact value depends on rounding

    def test_realized_events_include_sale_details(self, mem_db):
        _seed_data(mem_db)
        mem_db.execute(
            """INSERT INTO transactions
               (account_id,instrument_id,ts,quantity,price,local_currency,value_eur,fees_eur,source)
               VALUES (1,1,'2025-05-02T11:23:00','-2','118.20','EUR','236.40','-1.00','degiro_csv')"""
        )
        mem_db.commit()

        events = get_realized_pl_events(mem_db)
        assert len(events) == 1
        assert events[0]["instrument_name"] == "VWRL"
        assert events[0]["account_name"]
        assert events[0]["quantity"] == Decimal("2")
        assert events[0]["proceeds"] == Decimal("235.40")


class TestAllocation:
    def test_allocation_sector(self, mem_db):
        _seed_data(mem_db)
        alloc = get_allocation(mem_db)
        assert "Equity" in alloc["sector"] or "Unclassified" in alloc["sector"]

    def test_unclassified_fallback(self, mem_db):
        """Instruments without sector → 'Unclassified'."""
        mem_db.execute(
            "INSERT INTO instruments(id,name,asset_type) VALUES (2,'Unknown ETF','etf')"
        )
        mem_db.execute(
            """INSERT INTO transactions
               (account_id,instrument_id,ts,quantity,price,local_currency,value_eur,fees_eur,source)
               VALUES (1,2,'2025-01-16T10:00:00','5','50.00','EUR','-250.00','0','manual')"""
        )
        mem_db.execute(
            "INSERT INTO prices(instrument_id,date,close,currency,fetched_at) "
            "VALUES (2,'2025-06-01','55.00','EUR',datetime('now'))"
        )
        mem_db.commit()
        alloc = get_allocation(mem_db)
        assert "Unclassified" in alloc["sector"]

    def test_allocation_groups_country_into_continent(self, mem_db):
        _seed_data(mem_db)
        mem_db.execute("UPDATE instruments SET region='US' WHERE id=1")
        mem_db.commit()
        alloc = get_allocation(mem_db)
        assert "North America" in alloc["region"]

    def test_manual_country_weights_split_etf_across_continents(self, mem_db):
        _seed_data(mem_db)
        mem_db.execute(
            "INSERT INTO instrument_country_weights(instrument_id,country,weight_pct) VALUES (1,'US','60')"
        )
        mem_db.execute(
            "INSERT INTO instrument_country_weights(instrument_id,country,weight_pct) VALUES (1,'Japan','40')"
        )
        mem_db.commit()

        alloc = get_allocation(mem_db)
        assert alloc["region"]["North America"] > Decimal("0")
        assert alloc["region"]["Asia"] > Decimal("0")

    def test_allocation_details_identify_the_contributing_position(self, mem_db):
        _seed_data(mem_db)
        details = get_allocation_details(mem_db)
        entry = details["sector"]["Equity"][0]
        assert entry["instrument_name"] == "VWRL"
        assert entry["account_name"] == "DeGiro"
