"""Tests for first-installation authentication safeguards."""
from __future__ import annotations

from app.auth import complete_initial_setup, issue_initial_setup_token, verify_initial_setup_token


def test_generated_setup_token_is_required_and_one_time(mem_db, monkeypatch):
    monkeypatch.delenv("PM_SETUP_TOKEN", raising=False)

    token = issue_initial_setup_token(mem_db)

    assert token
    assert not verify_initial_setup_token(mem_db, "wrong-token")
    assert verify_initial_setup_token(mem_db, token)

    complete_initial_setup(mem_db)
    assert not verify_initial_setup_token(mem_db, token)


def test_configured_setup_token_overrides_generated_token(mem_db, monkeypatch):
    monkeypatch.setenv("PM_SETUP_TOKEN", "chosen-setup-token")

    assert issue_initial_setup_token(mem_db) is None
    assert verify_initial_setup_token(mem_db, "chosen-setup-token")
    assert not verify_initial_setup_token(mem_db, "incorrect")
