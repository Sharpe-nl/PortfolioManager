"""Small in-process scheduler for automatic stock and crypto refreshes."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..db import _open, get_setting, set_setting
from .bitvavo import sync_bitvavo
from .credentials import get_bitvavo_credentials
from .prices import refresh_all_prices

log = logging.getLogger("portfoliomanager.scheduler")
DEFAULT_REFRESH_TIMES = ("06:00", "18:00")
DEFAULT_REFRESH_TIMEZONE = "Europe/Amsterdam"


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


def get_refresh_timezone(conn) -> ZoneInfo:
    """Return the configured IANA timezone, safely defaulting to Amsterdam."""
    name = get_setting(conn, "automatic_refresh_timezone", DEFAULT_REFRESH_TIMEZONE)
    try:
        return ZoneInfo(name or DEFAULT_REFRESH_TIMEZONE)
    except ZoneInfoNotFoundError:
        return ZoneInfo(DEFAULT_REFRESH_TIMEZONE)


def save_refresh_timezone(conn, value: str) -> str:
    """Validate and persist an IANA timezone name such as Europe/Amsterdam."""
    name = value.strip()
    try:
        timezone = ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("Invalid IANA timezone") from exc
    set_setting(conn, "automatic_refresh_timezone", timezone.key)
    return timezone.key


def refresh_if_due(conn, now: datetime | None = None) -> dict:
    """Run a scheduled refresh once per configured timezone's local-time slot."""
    configured_timezone = get_refresh_timezone(conn)
    if now is None:
        now = datetime.now(timezone.utc).astimezone(configured_timezone)
    elif now.tzinfo is None:
        # A naive test/manual timestamp is interpreted as local time in the
        # configured timezone, avoiding dependence on the host's system zone.
        now = now.replace(tzinfo=configured_timezone)
    else:
        now = now.astimezone(configured_timezone)
    current_time = now.strftime("%H:%M")
    if current_time not in get_refresh_times(conn):
        return {"ran": False, "reason": "not_due"}

    slot = f"{configured_timezone.key}:{now.date().isoformat()}T{current_time}"
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
