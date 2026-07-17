"""Database helpers: connection factory, migration runner, settings accessors."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Generator

_DB_PATH = Path(__file__).parent.parent / "data" / "portfolio.db"
_MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


# ---------------------------------------------------------------------------
# Connection factory
# ---------------------------------------------------------------------------

def _open() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: required because FastAPI runs sync dependencies
    # (get_db) in a thread-pool worker but the connection is then used in the
    # async route handler (event loop thread).  Per-request connections mean
    # only one coroutine ever holds a given connection, so this is safe.
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def get_db() -> Generator[sqlite3.Connection, None, None]:
    """FastAPI dependency: yields a connection, commits on success, rolls back on error."""
    conn = _open()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Migration runner
# ---------------------------------------------------------------------------

def run_migrations() -> None:
    """Apply any unapplied *.sql files from migrations/ in lexicographic order."""
    conn = _open()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS _migrations "
        "(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    conn.commit()
    applied: set[str] = {r[0] for r in conn.execute("SELECT name FROM _migrations")}
    for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        if path.name not in applied:
            conn.executescript(path.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO _migrations(name, applied_at) VALUES (?, datetime('now'))",
                (path.name,),
            )
            conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------

def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
