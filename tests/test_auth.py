"""Tests for first-installation authentication safeguards."""
from __future__ import annotations

import pytest

from app.auth import (
    add_local_credential,
    complete_initial_setup,
    has_any_credentials,
    issue_initial_setup_token,
    clear_password_login_failures,
    password_login_is_limited,
    record_password_login_failure,
    verify_initial_setup_token,
    verify_local_credential,
)
from app.helpers import lan_mode_enabled


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


def test_local_password_is_salted_hashed_and_verified(mem_db):
    password = "a long, unique test password"
    add_local_credential(mem_db, "owner", password)

    stored = mem_db.execute("SELECT password_hash FROM local_credentials").fetchone()["password_hash"]
    assert stored.startswith("scrypt$16384$8$1$")
    assert password not in stored
    assert has_any_credentials(mem_db)
    assert verify_local_credential(mem_db, "owner", password)
    assert not verify_local_credential(mem_db, "owner", "incorrect password")
    assert not verify_local_credential(mem_db, "unknown", password)


def test_local_password_rejects_weak_password_and_invalid_username(mem_db):
    with pytest.raises(ValueError):
        add_local_credential(mem_db, "owner", "short")
    with pytest.raises(ValueError):
        add_local_credential(mem_db, "has space", "a long, unique test password")


def test_lan_mode_requires_explicit_http_opt_in(monkeypatch):
    monkeypatch.setenv("PM_LAN_MODE", "true")
    monkeypatch.setenv("PM_HTTPS_ONLY", "false")
    assert lan_mode_enabled()

    monkeypatch.setenv("PM_HTTPS_ONLY", "true")
    assert not lan_mode_enabled()


def test_password_login_rate_limit_blocks_after_five_failures():
    client_ip, username, now = "192.0.2.10", "owner", 1000.0
    clear_password_login_failures(client_ip, username)

    for _ in range(5):
        record_password_login_failure(client_ip, username, now=now)

    assert password_login_is_limited(client_ip, username, now=now)
    assert password_login_is_limited(client_ip, username, now=now + 899)
    assert not password_login_is_limited(client_ip, username, now=now + 900)


def test_successful_password_login_state_can_be_cleared():
    client_ip, username, now = "192.0.2.11", "owner", 1000.0
    for _ in range(5):
        record_password_login_failure(client_ip, username, now=now)

    clear_password_login_failures(client_ip, username)
    assert not password_login_is_limited(client_ip, username, now=now)
