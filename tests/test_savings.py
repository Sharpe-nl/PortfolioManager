"""Savings interest and dashboard visibility tests."""
from datetime import date
from decimal import Decimal

from app.routers.savings import _cash_movements, _signed_cash_amount
from app.services.savings import account_interest, savings_accounts, savings_value_series
from app.services.portfolio import get_allocation, get_cash_balances, get_portfolio_summary


def _savings_account(conn):
    conn.execute("INSERT INTO accounts(id,name,type,currency) VALUES(2,'Savings','savings','EUR')")
    conn.execute("INSERT INTO balance_snapshots(account_id,date,balance_eur) VALUES(2,'2026-01-01','1000')")
    conn.execute("INSERT INTO savings_interest_rates(account_id,annual_rate,payout_frequency,starts_on) VALUES(2,'12','monthly','2026-01-01')")
    conn.commit()


def test_monthly_interest_compounds_from_latest_snapshot(mem_db):
    _savings_account(mem_db)
    result = account_interest(mem_db, 2, date(2026, 3, 2))
    # 1% in February and 1% again in March: 1000 -> 1010 -> 1020.10
    assert result["balance"] == Decimal("1020.10")
    assert result["interest"] == Decimal("20.10")
    assert len(result["events"]) == 2


def test_manual_interest_is_an_editable_correction(mem_db):
    _savings_account(mem_db)
    mem_db.execute("INSERT INTO savings_interest_adjustments(account_id,date,amount_eur,description) VALUES(2,'2026-03-01','5','Bank correction')")
    mem_db.commit()
    result = account_interest(mem_db, 2, date(2026, 3, 2))
    # The correction is available before that day's monthly payout, so it
    # also earns interest in the next compounding step.
    assert result["balance"] == Decimal("1025.15")
    assert any(event["kind"] == "manual" for event in result["events"])


def test_interest_correction_on_snapshot_date_is_included(mem_db):
    _savings_account(mem_db)
    mem_db.execute("INSERT INTO savings_interest_adjustments(account_id,date,amount_eur) VALUES(2,'2026-01-01','1000')")
    mem_db.commit()
    result = account_interest(mem_db, 2, date(2026, 1, 2))
    assert result["balance"] == Decimal("2000.00")


def test_deposit_and_withdrawal_change_savings_balance(mem_db):
    _savings_account(mem_db)
    mem_db.execute("INSERT INTO cash_events(account_id,ts,type,amount_eur) VALUES(2,'2026-01-01T00:00:00','deposit','200')")
    mem_db.execute("INSERT INTO cash_events(account_id,ts,type,amount_eur) VALUES(2,'2026-01-02T00:00:00','withdrawal','-50')")
    mem_db.commit()
    result = account_interest(mem_db, 2, date(2026, 1, 2))
    assert result["balance"] == Decimal("1150.00")
    assert {event["kind"] for event in result["events"]} >= {"deposit", "withdrawal"}


def test_savings_cash_movements_are_available_to_settings(mem_db):
    _savings_account(mem_db)
    mem_db.execute("INSERT INTO cash_events(account_id,ts,type,amount_eur) VALUES(2,'2026-03-01T00:00:00','deposit','250')")
    mem_db.execute("INSERT INTO cash_events(account_id,ts,type,amount_eur) VALUES(2,'2026-03-02T00:00:00','withdrawal','-75')")
    mem_db.commit()
    movements = _cash_movements(mem_db, 2)
    assert [(row["date"], row["type"], row["amount_eur"]) for row in movements] == [
        ("2026-03-02", "withdrawal", "75"),
        ("2026-03-01", "deposit", "250"),
    ]


def test_savings_cash_amount_uses_movement_direction():
    assert _signed_cash_amount("125.50", "deposit") == "125.50"
    assert _signed_cash_amount("125.50", "withdrawal") == "-125.50"
    assert _signed_cash_amount("0", "deposit") is None


def test_first_deposit_can_create_a_savings_balance_without_snapshot(mem_db):
    mem_db.execute("INSERT INTO accounts(id,name,type,currency) VALUES(3,'Fresh savings','savings','EUR')")
    mem_db.execute("INSERT INTO cash_events(account_id,ts,type,amount_eur) VALUES(3,'2026-01-01T00:00:00','deposit','250')")
    mem_db.commit()
    result = account_interest(mem_db, 3, date(2026, 1, 2))
    assert result["balance"] == Decimal("250.00")


def test_savings_value_series_starts_from_balance_and_carries_interest(mem_db):
    _savings_account(mem_db)

    series = savings_value_series(mem_db)

    assert series[0] == {"date": "2026-01-01", "value": Decimal("1000.00")}
    assert series[-1]["value"] == account_interest(mem_db, 2)["balance"]


def test_bonus_rate_applies_only_to_the_balance_above_its_threshold(mem_db):
    _savings_account(mem_db)
    mem_db.execute("UPDATE savings_interest_rates SET annual_rate='1.5', payout_frequency='monthly' WHERE account_id=2")
    mem_db.execute("INSERT INTO savings_interest_rate_tiers(rate_id,min_balance_eur,annual_rate) VALUES(1,'19000','3')")
    mem_db.execute("UPDATE balance_snapshots SET balance_eur='20000' WHERE account_id=2")
    mem_db.commit()
    result = account_interest(mem_db, 2, date(2026, 2, 2))
    # €19,000 at 1.5% and €1,000 at 3%, paid monthly.
    assert result["interest"] == Decimal("26.25")


def test_ended_rate_stops_before_new_rate_starts(mem_db):
    _savings_account(mem_db)
    mem_db.execute("UPDATE savings_interest_rates SET ends_on='2026-01-07' WHERE account_id=2")
    mem_db.execute("INSERT INTO savings_interest_rates(account_id,annual_rate,payout_frequency,starts_on) VALUES(2,'52','weekly','2026-01-08')")
    mem_db.commit()
    result = account_interest(mem_db, 2, date(2026, 1, 16))
    assert result["interest"] == Decimal("10.00")


def test_hidden_savings_is_not_returned_for_dashboard(mem_db):
    _savings_account(mem_db)
    mem_db.execute("UPDATE accounts SET include_in_dashboard=0 WHERE id=2")
    mem_db.commit()
    assert savings_accounts(mem_db, include_hidden=False) == []


def test_savings_stays_out_of_portfolio_total_and_allocation(mem_db):
    _savings_account(mem_db)
    assert get_portfolio_summary(mem_db)["total_value"] == Decimal("0")
    assert "savings" not in get_allocation(mem_db)["asset_type"]


def test_savings_is_not_listed_as_broker_cash_when_excluded(mem_db):
    _savings_account(mem_db)
    assert get_cash_balances(mem_db, include_savings=False) == []
