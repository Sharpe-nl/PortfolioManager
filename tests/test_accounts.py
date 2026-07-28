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
