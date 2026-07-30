"""Safety checks for first-run database restoration."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.routers.settings import (
    _local_security_snapshot,
    _remove_crypto_backup_data,
    _remove_local_security,
    _restore_allowed,
    _restore_local_security,
    _validate_backup,
)


def test_restore_is_not_allowed_when_portfolio_data_exists(mem_db):
    assert not _restore_allowed(mem_db)


def test_valid_backup_passes_validation(mem_db, tmp_path):
    mem_db.execute("CREATE TABLE _migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    migrations = Path(__file__).parent.parent / "migrations"
    mem_db.executemany(
        "INSERT INTO _migrations(name, applied_at) VALUES (?, '2026-01-01')",
        [(path.name,) for path in migrations.glob("*.sql")],
    )
    mem_db.commit()
    path = tmp_path / "portfolio-backup.db"
    target = sqlite3.connect(path)
    mem_db.backup(target)
    target.close()

    _validate_backup(str(path))


def test_non_database_backup_is_rejected(tmp_path):
    path = tmp_path / "not-a-backup.db"
    path.write_text("not a sqlite database", encoding="utf-8")

    with pytest.raises(sqlite3.Error):
        _validate_backup(str(path))


def test_restore_keeps_current_installation_security(mem_db):
    """A restored old backup must never replace the current login methods."""
    mem_db.execute(
        "INSERT INTO webauthn_credentials "
        "(id, credential_id, public_key, sign_count, user_handle, created_at, name) "
        "VALUES (1, ?, ?, 0, ?, '2026-01-01', 'Current key')",
        (b"current-credential", b"current-key", b"current-user"),
    )
    mem_db.execute(
        "INSERT INTO local_credentials (id, username, password_hash) VALUES (1, 'current-user', 'current-hash')"
    )
    mem_db.execute("INSERT INTO settings(key, value) VALUES ('session_secret', 'current-session')")
    snapshot = _local_security_snapshot(mem_db)

    _remove_local_security(mem_db)
    mem_db.execute(
        "INSERT INTO webauthn_credentials "
        "(id, credential_id, public_key, sign_count, user_handle, created_at, name) "
        "VALUES (2, ?, ?, 0, ?, '2026-01-01', 'Backup key')",
        (b"backup-credential", b"backup-key", b"backup-user"),
    )
    mem_db.execute(
        "INSERT INTO local_credentials (id, username, password_hash) VALUES (2, 'backup-user', 'backup-hash')"
    )
    mem_db.execute("INSERT INTO settings(key, value) VALUES ('session_secret', 'backup-session')")

    _restore_local_security(mem_db, snapshot)

    assert [tuple(row) for row in mem_db.execute("SELECT username, password_hash FROM local_credentials")] == [
        ("current-user", "current-hash")
    ]
    assert [tuple(row) for row in mem_db.execute("SELECT name FROM webauthn_credentials")] == [("Current key",)]
    assert mem_db.execute("SELECT value FROM settings WHERE key='session_secret'").fetchone()[0] == "current-session"


def test_security_data_is_removed_from_export_copy(mem_db):
    mem_db.execute(
        "INSERT INTO local_credentials (username, password_hash) VALUES ('user', 'hash')"
    )
    mem_db.execute(
        "INSERT INTO settings(key, value) VALUES ('bitvavo_api_secret_encrypted', 'encrypted')"
    )

    _remove_local_security(mem_db)

    assert mem_db.execute("SELECT COUNT(*) FROM local_credentials").fetchone()[0] == 0
    assert mem_db.execute("SELECT COUNT(*) FROM webauthn_credentials").fetchone()[0] == 0
    assert mem_db.execute(
        "SELECT COUNT(*) FROM settings WHERE key='bitvavo_api_secret_encrypted'"
    ).fetchone()[0] == 0


def test_crypto_data_is_removed_from_portable_backup(mem_db):
    mem_db.execute(
        "INSERT INTO crypto_assets(symbol, name) VALUES ('BTC', 'Bitcoin')"
    )
    mem_db.execute(
        "INSERT INTO crypto_balances(symbol, available, value_eur, updated_at) VALUES ('BTC', '1', '100', '2026-01-01')"
    )
    mem_db.execute(
        "INSERT INTO crypto_transactions(transaction_id, executed_at, type) VALUES ('transaction', '2026-01-01', 'buy')"
    )
    mem_db.execute(
        "INSERT INTO crypto_prices(symbol, date, close_eur) VALUES ('BTC', '2026-01-01', '100')"
    )
    mem_db.execute(
        "INSERT INTO crypto_portfolio_snapshots(captured_at, total_eur, crypto_eur, cash_eur) VALUES ('2026-01-01', '100', '100', '0')"
    )

    _remove_crypto_backup_data(mem_db)

    for table in ("crypto_assets", "crypto_balances", "crypto_transactions", "crypto_prices", "crypto_portfolio_snapshots"):
        assert mem_db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
