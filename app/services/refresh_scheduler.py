"""Small in-process scheduler for automatic stock and crypto refreshes."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from ..db import _open, get_setting, set_setting
from .bitvavo import sync_bitvavo
from .credentials import get_bitvavo_credentials
from .prices import refresh_all_prices

log = logging.getLogger("portfoliomanager.scheduler")
DEFAULT_REFRESH_TIMES = ("06:00", "18:00")


def _valid_time(value: str) -> bool:
    try:
        parsed = datetime.strptime(value, "%H:%M")
    except (TypeError, ValueError):
        return False
    return parsed.strftime("%H:%M") == value


def get_refresh_times(conn) -> tuple[str, ...]:
    raw = get_setting(conn, "automatic_refresh_times", ",".join(DEFAULT_REFRESH_TIMES)) or ""
    values = tuple(dict.fromkeys(part.strip() for part in raw.split(",") if _valid_time(part.strip())))
    return values or DEFAULT_REFRESH_TIMES


def save_refresh_times(conn, values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(value.strip() for value in values if _valid_time(value.strip())))
    if not normalized:
        raise ValueError("At least one valid HH:MM time is required")
    set_setting(conn, "automatic_refresh_times", ",".join(sorted(normalized)))
    return tuple(sorted(normalized))


def refresh_if_due(conn, now: datetime | None = None) -> dict:
    """Run a scheduled refresh once per configured local-time slot."""
    now = now or datetime.now().astimezone()
    current_time = now.strftime("%H:%M")
    if current_time not in get_refresh_times(conn):
        return {"ran": False, "reason": "not_due"}

    slot = f"{now.date().isoformat()}T{current_time}"
    if get_setting(conn, "automatic_refresh_last_slot") == slot:
        return {"ran": False, "reason": "already_ran"}
    set_setting(conn, "automatic_refresh_last_slot", slot)
    conn.commit()

    result: dict = {"ran": True, "slot": slot}
    try:
        result["stocks"] = refresh_all_prices(conn, period="5d", force=True)
    except Exception as exc:  # keep crypto independent from a stock-provider failure
        log.exception("Scheduled stock refresh failed")
        result["stocks"] = {"error": str(exc)[:180]}

    try:
        credentials = get_bitvavo_credentials(conn)
        result["crypto"] = sync_bitvavo(conn, *credentials) if credentials else {"skipped": "not_configured"}
    except Exception as exc:  # credentials/network failures must not stop future runs
        log.exception("Scheduled crypto refresh failed")
        result["crypto"] = {"error": str(exc)[:180]}

    set_setting(conn, "automatic_refresh_last_run", now.isoformat(timespec="minutes"))
    set_setting(conn, "automatic_refresh_last_result", json.dumps(result, default=str))
    conn.commit()
    return result


def run_due_refresh() -> dict:
    conn = _open()
    try:
        return refresh_if_due(conn)
    finally:
        conn.close()


async def scheduler_loop() -> None:
    """Check once per minute so changed settings take effect immediately."""
    while True:
        try:
            await asyncio.to_thread(run_due_refresh)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Automatic refresh scheduler check failed")
        now = datetime.now().astimezone()
        await asyncio.sleep(max(1, 60 - now.second))
