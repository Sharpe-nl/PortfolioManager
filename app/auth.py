"""WebAuthn / FIDO2 helpers (YubiKey authentication).

Registration flow
-----------------
1. GET  /auth/register  → render page (only when no credentials exist yet)
2. POST /auth/register/options  → generate & store challenge, return JSON
3. POST /auth/register/verify   → verify response, persist credential

Authentication flow
-------------------
1. GET  /auth/login             → render page
2. POST /auth/login/options     → generate & store challenge, return JSON
3. POST /auth/login/verify      → verify response, set session['authenticated']
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from .db import get_setting, set_setting

RP_NAME = "PortfolioManager"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_rp_id(conn: sqlite3.Connection, request_host: str) -> str:
    """Return the configured RP ID; default = request hostname stripped of port."""
    configured = get_setting(conn, "webauthn_rp_id")
    if configured:
        return configured
    return request_host.split(":")[0]


def get_user_handle(conn: sqlite3.Connection) -> bytes:
    """Stable random user handle (generated once, stored in settings)."""
    stored = get_setting(conn, "webauthn_user_handle")
    if stored:
        return bytes.fromhex(stored)
    handle = os.urandom(32)
    set_setting(conn, "webauthn_user_handle", handle.hex())
    conn.commit()
    return handle


def has_credentials(conn: sqlite3.Connection) -> bool:
    return conn.execute(
        "SELECT 1 FROM webauthn_credentials LIMIT 1"
    ).fetchone() is not None


def list_credentials(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, name, created_at FROM webauthn_credentials ORDER BY created_at"
    ).fetchall()
    return [{"id": r["id"], "name": r["name"], "created_at": r["created_at"]} for r in rows]


def delete_credential(conn: sqlite3.Connection, cred_pk_id: int) -> tuple[bool, str]:
    """Remove a registered credential. Refuses to remove the last one, since
    that would lock the owner out of a single-user app with no password
    fallback."""
    count = conn.execute("SELECT COUNT(*) AS n FROM webauthn_credentials").fetchone()["n"]
    if count <= 1:
        return False, "Kan de laatste sleutel niet verwijderen — je zou jezelf buitensluiten."
    cur = conn.execute("DELETE FROM webauthn_credentials WHERE id=?", (cred_pk_id,))
    return cur.rowcount > 0, ""


def _stored_descriptors(conn: sqlite3.Connection) -> list[PublicKeyCredentialDescriptor]:
    rows = conn.execute(
        "SELECT credential_id, transports FROM webauthn_credentials"
    ).fetchall()
    result = []
    for row in rows:
        transports = json.loads(row["transports"]) if row["transports"] else None
        result.append(
            PublicKeyCredentialDescriptor(id=bytes(row["credential_id"]), transports=transports)
        )
    return result


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def begin_registration(conn: sqlite3.Connection, rp_id: str) -> dict[str, Any]:
    """Generate registration options; caller must store the challenge in the session.

    Excludes already-registered credentials so the browser can warn if the
    owner tries to add the same physical key twice (relevant once one or
    more keys already exist; harmless — an empty list — on first setup).
    """
    user_handle = get_user_handle(conn)
    opts = generate_registration_options(
        rp_id=rp_id,
        rp_name=RP_NAME,
        user_id=user_handle,
        user_name="owner",
        user_display_name="Portfolio Owner",
        exclude_credentials=_stored_descriptors(conn),
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    return {
        "options_json": options_to_json(opts),
        "challenge_b64": bytes_to_base64url(opts.challenge),
    }


def finish_registration(
    conn: sqlite3.Connection,
    rp_id: str,
    expected_origin: str,
    credential_json: str,
    expected_challenge: bytes,
    name: str | None = None,
) -> None:
    """Verify and persist a new WebAuthn credential."""
    verification = verify_registration_response(
        credential=credential_json,
        expected_challenge=expected_challenge,
        expected_rp_id=rp_id,
        expected_origin=expected_origin,
        require_user_verification=False,
    )
    conn.execute(
        """INSERT INTO webauthn_credentials
               (credential_id, public_key, sign_count, user_handle, transports, created_at, name)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            verification.credential_id,
            verification.credential_public_key,
            verification.sign_count,
            get_user_handle(conn),
            None,
            datetime.now(timezone.utc).isoformat(),
            name,
        ),
    )


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def begin_authentication(conn: sqlite3.Connection, rp_id: str) -> dict[str, Any]:
    """Generate authentication options; caller must store the challenge in the session."""
    opts = generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=_stored_descriptors(conn),
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    return {
        "options_json": options_to_json(opts),
        "challenge_b64": bytes_to_base64url(opts.challenge),
    }


def finish_authentication(
    conn: sqlite3.Connection,
    rp_id: str,
    expected_origin: str,
    credential_json: str,
    expected_challenge: bytes,
) -> bool:
    """Verify authentication response; update sign count; return True on success."""
    response_data = json.loads(credential_json)
    raw_id = base64url_to_bytes(response_data["rawId"])

    row = conn.execute(
        "SELECT credential_id, public_key, sign_count "
        "FROM webauthn_credentials WHERE credential_id=?",
        (raw_id,),
    ).fetchone()
    if not row:
        return False

    verification = verify_authentication_response(
        credential=credential_json,
        expected_challenge=expected_challenge,
        expected_rp_id=rp_id,
        expected_origin=expected_origin,
        credential_public_key=bytes(row["public_key"]),
        credential_current_sign_count=row["sign_count"],
        require_user_verification=False,
    )
    conn.execute(
        "UPDATE webauthn_credentials SET sign_count=? WHERE credential_id=?",
        (verification.new_sign_count, raw_id),
    )
    return True
