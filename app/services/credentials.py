"""Encrypted storage for external-service credentials.

The encryption key lives next to, but outside, the SQLite database. This
keeps API secrets out of database backups while retaining a self-contained
self-hosted setup. Deployments may supply PM_CREDENTIAL_KEY instead.
"""
from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from ..db import _DB_PATH, get_setting, set_setting

_KEY_PATH = Path(_DB_PATH).parent / ".credential_key"


class CredentialError(RuntimeError):
    """A stored credential cannot be encrypted or decrypted."""


def _credential_key() -> bytes:
    configured = os.getenv("PM_CREDENTIAL_KEY", "").strip()
    if configured:
        return configured.encode("ascii")
    if _KEY_PATH.exists():
        return _KEY_PATH.read_bytes().strip()
    _KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    descriptor = os.open(_KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(key)
    return key


def encrypt_value(value: str, key: bytes | None = None) -> str:
    try:
        return Fernet(key or _credential_key()).encrypt(value.encode("utf-8")).decode("ascii")
    except (ValueError, TypeError) as exc:
        raise CredentialError("Invalid credential encryption key") from exc


def decrypt_value(value: str, key: bytes | None = None) -> str:
    try:
        return Fernet(key or _credential_key()).decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError) as exc:
        raise CredentialError("Stored credential could not be decrypted") from exc


def save_bitvavo_credentials(conn, api_key: str, api_secret: str) -> None:
    set_setting(conn, "bitvavo_api_key_encrypted", encrypt_value(api_key))
    set_setting(conn, "bitvavo_api_secret_encrypted", encrypt_value(api_secret))


def get_bitvavo_credentials(conn) -> tuple[str, str] | None:
    env_key = os.getenv("BITVAVO_API_KEY", "").strip()
    env_secret = os.getenv("BITVAVO_API_SECRET", "").strip()
    if env_key and env_secret:
        return env_key, env_secret
    key_token = get_setting(conn, "bitvavo_api_key_encrypted")
    secret_token = get_setting(conn, "bitvavo_api_secret_encrypted")
    if not key_token or not secret_token:
        return None
    return decrypt_value(key_token), decrypt_value(secret_token)


def has_bitvavo_credentials(conn) -> bool:
    if os.getenv("BITVAVO_API_KEY", "").strip() and os.getenv("BITVAVO_API_SECRET", "").strip():
        return True
    return bool(get_setting(conn, "bitvavo_api_key_encrypted") and get_setting(conn, "bitvavo_api_secret_encrypted"))


def clear_bitvavo_credentials(conn) -> None:
    conn.execute("DELETE FROM settings WHERE key IN ('bitvavo_api_key_encrypted','bitvavo_api_secret_encrypted')")
