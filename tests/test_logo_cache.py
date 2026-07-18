"""Local Logo.dev cache tests without network access."""
from __future__ import annotations

from app.db import set_setting
from app.services import logo_cache


def test_logo_is_downloaded_once_then_served_from_local_cache(mem_db, monkeypatch, tmp_path):
    monkeypatch.setattr(logo_cache, "_LOGO_CACHE_DIR", tmp_path)
    set_setting(mem_db, "logo_dev_token", "publishable-demo-key")
    calls = []

    def fetcher(url):
        calls.append(url)
        return b"\x89PNG\r\n\x1a\nlocal-logo"

    first = logo_cache.get_cached_logo(mem_db, "ticker", "ASML.AS", fetcher)
    second = logo_cache.get_cached_logo(mem_db, "ticker", "ASML.AS", fetcher)

    assert first == second
    assert first and first.read_bytes().startswith(b"\x89PNG")
    assert len(calls) == 1


def test_missing_logo_is_cached_without_retrying_provider(mem_db, monkeypatch, tmp_path):
    monkeypatch.setattr(logo_cache, "_LOGO_CACHE_DIR", tmp_path)
    set_setting(mem_db, "logo_dev_token", "publishable-demo-key")
    calls = []

    def missing(_url):
        calls.append(True)
        from urllib.error import HTTPError
        raise HTTPError("https://img.logo.dev", 404, "Not found", {}, None)

    assert logo_cache.get_cached_logo(mem_db, "name", "Unknown Asset", missing) is None
    assert logo_cache.get_cached_logo(mem_db, "name", "Unknown Asset", missing) is None
    assert len(calls) == 1
