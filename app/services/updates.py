"""Version checks and the deliberately opt-in native self-update trigger."""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VERSION_FILE = PROJECT_ROOT / "VERSION"
REPOSITORY = "Sharpe-nl/PortfolioManager"
LATEST_VERSION_URL = f"https://raw.githubusercontent.com/{REPOSITORY}/main/VERSION"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$")
_SELF_UPDATE_COMMAND = (
    "/usr/bin/sudo", "-n", "/usr/bin/systemctl", "start", "--no-block",
    "portfoliomanager-update.service",
)


def current_version() -> str:
    """Return the version baked into this checkout."""
    return VERSION_FILE.read_text(encoding="utf-8").strip()


def _version_key(value: str) -> tuple[int, int, int, int, tuple[tuple[int, object], ...]]:
    """Parse the small SemVer subset used by the project.

    Stable releases sort after their corresponding prereleases. This keeps the
    update check dependency-free while still handling versions such as
    ``0.1.0-beta`` and ``0.1.0`` correctly.
    """
    match = _VERSION_RE.fullmatch(value)
    if not match:
        raise ValueError("Invalid version")
    major, minor, patch, prerelease = match.groups()
    prerelease_parts: list[tuple[int, object]] = []
    if prerelease:
        for part in prerelease.split("."):
            prerelease_parts.append((0, int(part)) if part.isdigit() else (1, part))
    return int(major), int(minor), int(patch), 1 if prerelease is None else 0, tuple(prerelease_parts)


def is_newer_version(candidate: str, installed: str) -> bool:
    """Whether *candidate* is newer than *installed*."""
    return _version_key(candidate) > _version_key(installed)


def check_for_update(fetch=None) -> dict[str, object]:
    """Fetch and validate the public version marker from the main branch."""
    installed = current_version()
    _version_key(installed)
    if fetch is None:
        def fetch(url: str) -> str:
            request = Request(url, headers={"User-Agent": "PortfolioManager-update-check"})
            with urlopen(request, timeout=8) as response:  # nosec B310: fixed HTTPS URL
                return response.read(128).decode("utf-8")

    try:
        latest = fetch(LATEST_VERSION_URL).strip()
        _version_key(latest)
    except Exception:
        return {
            "current_version": installed,
            "latest_version": None,
            "update_available": False,
            "error": True,
        }

    return {
        "current_version": installed,
        "latest_version": latest,
        "update_available": is_newer_version(latest, installed),
        "error": False,
    }


def self_update_enabled() -> bool:
    """Self-updating is off unless the server administrator opted in."""
    return os.getenv("PM_ENABLE_SELF_UPDATE", "false").lower() == "true"


def start_self_update() -> bool:
    """Ask the narrowly-authorised systemd unit to update a native install."""
    if not self_update_enabled():
        return False
    try:
        result = subprocess.run(
            _SELF_UPDATE_COMMAND,
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0
