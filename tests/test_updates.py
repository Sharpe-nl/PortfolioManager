"""Version comparison and self-update guard tests."""
from __future__ import annotations

from app.services import updates


def test_beta_and_stable_versions_sort_correctly():
    assert updates.is_newer_version("0.1.0", "0.1.0-beta") is True
    assert updates.is_newer_version("0.1.1-beta", "0.1.0") is True
    assert updates.is_newer_version("0.1.0-beta.2", "0.1.0-beta.1") is True
    assert updates.is_newer_version("0.1.0-beta", "0.1.0") is False


def test_check_for_update_handles_new_current_and_bad_remote_versions(tmp_path, monkeypatch):
    version_file = tmp_path / "VERSION"
    version_file.write_text("0.1.0-beta\n", encoding="utf-8")
    monkeypatch.setattr(updates, "VERSION_FILE", version_file)

    available = updates.check_for_update(lambda _: "0.1.0\n")
    assert available == {
        "current_version": "0.1.0-beta",
        "latest_version": "0.1.0",
        "update_available": True,
        "error": False,
    }

    current = updates.check_for_update(lambda _: "0.1.0-beta\n")
    assert current["update_available"] is False
    assert current["error"] is False

    invalid = updates.check_for_update(lambda _: "not-a-version")
    assert invalid["latest_version"] is None
    assert invalid["error"] is True


def test_self_update_requires_explicit_opt_in(monkeypatch):
    monkeypatch.delenv("PM_ENABLE_SELF_UPDATE", raising=False)
    assert updates.self_update_enabled() is False
    assert updates.start_self_update() is False

    monkeypatch.setenv("PM_ENABLE_SELF_UPDATE", "true")
    assert updates.self_update_enabled() is True
