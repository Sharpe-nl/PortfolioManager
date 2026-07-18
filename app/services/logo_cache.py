"""Fetch Logo.dev assets once and serve subsequent requests from local disk."""
from __future__ import annotations

import hashlib
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from ..db import _DB_PATH, get_setting

_LOGO_CACHE_DIR = Path(_DB_PATH).parent / "logos"
_MAX_LOGO_BYTES = 512 * 1024
_VALID_MODES = {"isin", "ticker", "name"}
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


class LogoFetchError(RuntimeError):
    """Logo.dev could not be reached or returned an unsafe response."""


def get_cached_logo(conn, mode: str, value: str, fetcher=None) -> Path | None:
    """Return a local PNG path, caching a successful or missing lookup.

    ``fetcher`` is injected in tests; production uses Logo.dev over HTTPS.
    """
    mode, value = _normalise(mode, value)
    lock = _lock_for(mode, value)
    with lock:
        cached = _cached_path(conn, mode, value)
        if cached is not ...:
            return cached

        token = get_setting(conn, "logo_dev_token") or os.getenv("PM_LOGO_DEV_TOKEN", "")
        if not token:
            return None
        url = (
            f"https://img.logo.dev/{mode}/{urllib.parse.quote(value, safe='')}"
            f"?token={urllib.parse.quote(token, safe='')}&size=64&format=png&fallback=404"
        )
        try:
            content = fetcher(url) if fetcher else _download_png(url)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                _remember(conn, mode, value, 404, None)
                return None
            raise LogoFetchError("Logo provider returned an error") from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise LogoFetchError("Logo provider is unavailable") from exc

        if not content or len(content) > _MAX_LOGO_BYTES:
            raise LogoFetchError("Logo provider returned an invalid image")
        filename = f"{hashlib.sha256(f'{mode}\0{value}'.encode('utf-8')).hexdigest()}.png"
        _LOGO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = _LOGO_CACHE_DIR / filename
        temp_path = path.with_suffix(".tmp")
        temp_path.write_bytes(content)
        temp_path.replace(path)
        _remember(conn, mode, value, 200, filename)
        return path


def clear_missing_logo_cache(conn) -> None:
    """Allow retries for previously missing assets after a key is changed."""
    conn.execute("DELETE FROM logo_cache WHERE status=404")


def _normalise(mode: str, value: str) -> tuple[str, str]:
    mode, value = mode.strip().lower(), value.strip()
    if mode not in _VALID_MODES or not value or len(value) > 200:
        raise ValueError("Invalid logo request")
    return mode, value


def _lock_for(mode: str, value: str) -> threading.Lock:
    key = f"{mode}\0{value}"
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def _cached_path(conn, mode: str, value: str) -> Path | None | object:
    row = conn.execute(
        "SELECT status, filename FROM logo_cache WHERE mode=? AND value=?", (mode, value)
    ).fetchone()
    if not row:
        return ...
    if row["status"] == 404:
        return None
    path = _LOGO_CACHE_DIR / str(row["filename"])
    if path.is_file():
        return path
    conn.execute("DELETE FROM logo_cache WHERE mode=? AND value=?", (mode, value))
    return ...


def _remember(conn, mode: str, value: str, status: int, filename: str | None) -> None:
    conn.execute(
        "INSERT INTO logo_cache(mode,value,status,filename,fetched_at) VALUES(?,?,?,?,datetime('now')) "
        "ON CONFLICT(mode,value) DO UPDATE SET status=excluded.status, filename=excluded.filename, fetched_at=excluded.fetched_at",
        (mode, value, status, filename),
    )
    conn.commit()


def _download_png(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"Accept": "image/png", "User-Agent": "PortfolioManager/logo-cache"})
    with urllib.request.urlopen(request, timeout=10) as response:
        content_type = response.headers.get_content_type()
        if content_type != "image/png":
            raise ValueError("Unexpected logo content type")
        return response.read(_MAX_LOGO_BYTES + 1)
