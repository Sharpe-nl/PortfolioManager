"""Safety checks for first-run database restoration."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.routers.settings import _restore_allowed, _validate_backup


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
