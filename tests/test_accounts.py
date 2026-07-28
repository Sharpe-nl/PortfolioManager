"""Account type safeguards."""
from __future__ import annotations

import asyncio

from app.routers import accounts as accounts_router


def test_other_account_type_cannot_be_created(mem_db):
    response = asyncio.run(
        accounts_router.add_account(None, mem_db, None, "Unsupported", "other", "EUR")
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/accounts?error=invalid_type"
    assert mem_db.execute("SELECT COUNT(*) FROM accounts WHERE type='other'").fetchone()[0] == 0


def test_account_delete_is_committed_before_redirect(mem_db):
    mem_db.execute("INSERT INTO accounts(id,name,type,currency) VALUES(2,'Temporary','broker','EUR')")
    mem_db.commit()

    response = asyncio.run(accounts_router.delete_account(2, conn=mem_db, _=None))

    assert response.headers["location"] == "/accounts"
    assert mem_db.execute("SELECT 1 FROM accounts WHERE id=2").fetchone() is None
    assert not mem_db.in_transaction
