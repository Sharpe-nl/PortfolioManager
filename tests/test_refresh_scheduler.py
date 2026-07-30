"""Automatic stock and crypto refresh schedule tests."""
from datetime import datetime, timezone

from app.db import get_setting
from app.services import refresh_scheduler as scheduler


def test_refresh_schedule_defaults_and_can_be_changed(mem_db):
    assert scheduler.get_refresh_times(mem_db) == ("06:00", "18:00")
    assert scheduler.get_refresh_timezone(mem_db).key == "Europe/Amsterdam"
    assert scheduler.save_refresh_times(mem_db, ["07:15", "21:30"]) == ("07:15", "21:30")
    assert scheduler.get_refresh_times(mem_db) == ("07:15", "21:30")
    assert scheduler.save_refresh_timezone(mem_db, "America/New_York") == "America/New_York"
    assert scheduler.get_refresh_timezone(mem_db).key == "America/New_York"


def test_due_slot_refreshes_stocks_and_crypto_only_once(mem_db, monkeypatch):
    calls = []
    monkeypatch.setattr(
        scheduler,
        "refresh_all_prices",
        lambda conn, period, force: calls.append(("stocks", period, force)) or {"refreshed": 2, "failed": []},
    )
    monkeypatch.setattr(scheduler, "get_bitvavo_credentials", lambda conn: ("key", "secret"))
    monkeypatch.setattr(
        scheduler,
        "sync_bitvavo",
        lambda conn, key, secret: calls.append(("crypto", key, secret)) or {"balances": 3},
    )

    due = datetime(2026, 7, 18, 6, 0)
    result = scheduler.refresh_if_due(mem_db, due)
    assert result["ran"] is True
    assert calls == [("stocks", "5d", True), ("crypto", "key", "secret")]
    assert get_setting(mem_db, "automatic_refresh_last_run") == "2026-07-18T06:00+02:00"

    assert scheduler.refresh_if_due(mem_db, due) == {"ran": False, "reason": "already_ran"}
    assert len(calls) == 2


def test_refresh_is_skipped_outside_configured_minutes(mem_db, monkeypatch):
    monkeypatch.setattr(scheduler, "refresh_all_prices", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))
    assert scheduler.refresh_if_due(mem_db, datetime(2026, 7, 18, 12, 0)) == {
        "ran": False,
        "reason": "not_due",
    }


def test_due_time_is_interpreted_in_configured_timezone(mem_db, monkeypatch):
    calls = []
    scheduler.save_refresh_timezone(mem_db, "America/New_York")
    monkeypatch.setattr(scheduler, "refresh_all_prices", lambda *args, **kwargs: calls.append("stocks") or {})
    monkeypatch.setattr(scheduler, "get_bitvavo_credentials", lambda conn: None)

    # 10:00 UTC is 06:00 in New York during daylight saving time.
    result = scheduler.refresh_if_due(mem_db, datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc))

    assert result["ran"] is True
    assert calls == ["stocks"]
