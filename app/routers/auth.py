"""WebAuthn authentication routes.

GET  /auth/register            → setup page (only when no credentials exist)
POST /auth/register/options    → generate registration options JSON
POST /auth/register/verify     → verify and persist credential
GET  /auth/login               → login page
POST /auth/login/options       → generate authentication options JSON
POST /auth/login/verify        → verify and set session
POST /auth/logout               → clear session
POST /auth/credentials/options → (logged in) start adding another key
POST /auth/credentials/verify   → (logged in) verify and persist another key
POST /auth/credentials/{id}/rename → (logged in) rename a key
POST /auth/credentials/{id}/delete → (logged in) remove a key
"""
from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..auth import (
    begin_authentication,
    begin_registration,
    add_local_credential,
    clear_password_login_failures,
    complete_initial_setup,
    delete_credential,
    finish_authentication,
    finish_registration,
    get_rp_id,
    has_credentials,
    has_local_credentials,
    has_any_credentials,
    password_login_is_limited,
    record_password_login_failure,
    set_local_password,
    verify_local_credential,
    verify_initial_setup_token,
)
from ..db import get_db
from ..helpers import templates as _templates, require_auth

router = APIRouter(prefix="/auth", tags=["auth"])
_SETUP_TOKEN_HEADER = "X-Setup-Token"


def _origin(request: Request) -> str:
    scheme = request.url.scheme
    host = request.headers.get("host", request.url.hostname or "localhost")
    return f"{scheme}://{host}"


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, conn=Depends(get_db)):
    if has_any_credentials(conn):
        return RedirectResponse(url="/auth/login", status_code=303)
    return _templates.TemplateResponse("register.html", {"request": request})


@router.post("/register/options")
async def register_options(request: Request, conn=Depends(get_db)):
    if has_any_credentials(conn):
        return JSONResponse({"error": "Already registered"}, status_code=400)
    if not verify_initial_setup_token(conn, request.headers.get(_SETUP_TOKEN_HEADER)):
        return JSONResponse({"error": "Invalid setup token"}, status_code=403)
    rp_id = get_rp_id(conn, request.headers.get("host", "localhost"))
    data = begin_registration(conn, rp_id)
    request.session["reg_challenge"] = data["challenge_b64"]
    return JSONResponse(json.loads(data["options_json"]))


@router.post("/register/verify")
async def register_verify(request: Request, conn=Depends(get_db)):
    if has_any_credentials(conn):
        return JSONResponse({"error": "Already registered"}, status_code=400)
    if not verify_initial_setup_token(conn, request.headers.get(_SETUP_TOKEN_HEADER)):
        return JSONResponse({"error": "Invalid setup token"}, status_code=403)

    challenge_b64 = request.session.pop("reg_challenge", None)
    if not challenge_b64:
        return JSONResponse({"error": "No active challenge"}, status_code=400)

    from webauthn.helpers import base64url_to_bytes
    try:
        body = await request.body()
        rp_id = get_rp_id(conn, request.headers.get("host", "localhost"))
        finish_registration(
            conn=conn,
            rp_id=rp_id,
            expected_origin=_origin(request),
            credential_json=body.decode(),
            expected_challenge=base64url_to_bytes(challenge_b64),
        )
        complete_initial_setup(conn)
        conn.commit()
        return JSONResponse({"ok": True})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@router.post("/register/password")
async def register_password(
    request: Request,
    setup_token: str = Form(""),
    username: str = Form(""),
    password: str = Form(""),
    confirm_password: str = Form(""),
    conn=Depends(get_db),
):
    if has_any_credentials(conn) or not verify_initial_setup_token(conn, setup_token):
        return RedirectResponse(url="/auth/register?password_error=invalid", status_code=303)
    if password != confirm_password:
        return RedirectResponse(url="/auth/register?password_error=mismatch", status_code=303)
    try:
        add_local_credential(conn, username, password)
        complete_initial_setup(conn)
        conn.commit()
    except (ValueError, sqlite3.IntegrityError):
        return RedirectResponse(url="/auth/register?password_error=invalid", status_code=303)
    return RedirectResponse(url="/auth/login?password_setup=1", status_code=303)


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, conn=Depends(get_db)):
    if not has_any_credentials(conn):
        return RedirectResponse(url="/auth/register", status_code=303)
    if request.session.get("authenticated"):
        return RedirectResponse(url="/", status_code=303)
    return _templates.TemplateResponse("login.html", {
        "request": request,
        "webauthn_available": has_credentials(conn),
        "password_available": has_local_credentials(conn),
    })


@router.post("/login/password")
async def password_login(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    conn=Depends(get_db),
):
    client_ip = request.client.host if request.client else "unknown"
    if password_login_is_limited(client_ip, username):
        return RedirectResponse(url="/auth/login?password_error=rate_limited", status_code=303)
    if verify_local_credential(conn, username, password):
        clear_password_login_failures(client_ip, username)
        request.session["authenticated"] = True
        return RedirectResponse(url="/", status_code=303)
    record_password_login_failure(client_ip, username)
    return RedirectResponse(url="/auth/login?password_error=1", status_code=303)


@router.post("/login/options")
async def login_options(request: Request, conn=Depends(get_db)):
    if not has_credentials(conn):
        return JSONResponse({"error": "No credentials registered"}, status_code=400)
    rp_id = get_rp_id(conn, request.headers.get("host", "localhost"))
    data = begin_authentication(conn, rp_id)
    request.session["auth_challenge"] = data["challenge_b64"]
    return JSONResponse(json.loads(data["options_json"]))


@router.post("/login/verify")
async def login_verify(request: Request, conn=Depends(get_db)):
    challenge_b64 = request.session.pop("auth_challenge", None)
    if not challenge_b64:
        return JSONResponse({"error": "No active challenge"}, status_code=400)

    from webauthn.helpers import base64url_to_bytes
    try:
        body = await request.body()
        rp_id = get_rp_id(conn, request.headers.get("host", "localhost"))
        ok = finish_authentication(
            conn=conn,
            rp_id=rp_id,
            expected_origin=_origin(request),
            credential_json=body.decode(),
            expected_challenge=base64url_to_bytes(challenge_b64),
        )
        conn.commit()
        if ok:
            request.session["authenticated"] = True
            return JSONResponse({"ok": True})
        return JSONResponse({"error": "Authentication failed"}, status_code=401)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


# ---------------------------------------------------------------------------
# Manage credentials (add / remove additional keys) — requires an existing
# authenticated session, unlike /register above which is only for the very
# first key on a fresh install.
# ---------------------------------------------------------------------------

@router.post("/credentials/options")
async def add_credential_options(request: Request, conn=Depends(get_db), _=Depends(require_auth)):
    rp_id = get_rp_id(conn, request.headers.get("host", "localhost"))
    data = begin_registration(conn, rp_id)
    request.session["add_cred_challenge"] = data["challenge_b64"]
    return JSONResponse(json.loads(data["options_json"]))


@router.post("/credentials/verify")
async def add_credential_verify(request: Request, conn=Depends(get_db), _=Depends(require_auth)):
    challenge_b64 = request.session.pop("add_cred_challenge", None)
    if not challenge_b64:
        return JSONResponse({"error": "No active challenge"}, status_code=400)

    name = (request.query_params.get("name") or "").strip() or None

    from webauthn.helpers import base64url_to_bytes
    try:
        body = await request.body()
        rp_id = get_rp_id(conn, request.headers.get("host", "localhost"))
        finish_registration(
            conn=conn,
            rp_id=rp_id,
            expected_origin=_origin(request),
            credential_json=body.decode(),
            expected_challenge=base64url_to_bytes(challenge_b64),
            name=name,
        )
        conn.commit()
        return JSONResponse({"ok": True})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@router.post("/credentials/{cred_id}/delete")
async def delete_credential_route(cred_id: int, conn=Depends(get_db), _=Depends(require_auth)):
    from urllib.parse import quote
    ok, error = delete_credential(conn, cred_id)
    if ok:
        conn.commit()
        return RedirectResponse(url="/settings?saved=1", status_code=303)
    return RedirectResponse(url=f"/settings?cred_error={quote(error)}", status_code=303)


@router.post("/credentials/{cred_id}/rename")
async def rename_credential_route(
    cred_id: int,
    request: Request,
    conn=Depends(get_db),
    _=Depends(require_auth),
):
    """Update the display name of a registered security key."""
    form = await request.form()
    name = str(form.get("name", "")).strip() or None
    conn.execute("UPDATE webauthn_credentials SET name=? WHERE id=?", (name, cred_id))
    return RedirectResponse(url="/settings?saved=1", status_code=303)


@router.post("/local-credentials")
async def add_local_credential_route(
    username: str = Form(""), password: str = Form(""), confirm_password: str = Form(""),
    conn=Depends(get_db), _=Depends(require_auth),
):
    if password != confirm_password:
        return RedirectResponse(url="/settings?password_error=mismatch", status_code=303)
    try:
        add_local_credential(conn, username, password)
        conn.commit()
    except (ValueError, sqlite3.IntegrityError):
        return RedirectResponse(url="/settings?password_error=invalid", status_code=303)
    return RedirectResponse(url="/settings?saved=1", status_code=303)


@router.post("/local-credentials/{credential_id}/password")
async def update_local_password_route(
    credential_id: int, password: str = Form(""), confirm_password: str = Form(""),
    conn=Depends(get_db), _=Depends(require_auth),
):
    if password != confirm_password:
        return RedirectResponse(url="/settings?password_error=mismatch", status_code=303)
    try:
        if not set_local_password(conn, credential_id, password):
            return RedirectResponse(url="/settings?password_error=invalid", status_code=303)
        conn.commit()
    except ValueError:
        return RedirectResponse(url="/settings?password_error=invalid", status_code=303)
    return RedirectResponse(url="/settings?saved=1", status_code=303)


@router.post("/local-credentials/{credential_id}/delete")
async def delete_local_credential_route(credential_id: int, conn=Depends(get_db), _=Depends(require_auth)):
    count = conn.execute("SELECT COUNT(*) AS n FROM local_credentials").fetchone()["n"]
    if count <= 1 and not has_credentials(conn):
        return RedirectResponse(url="/settings?password_error=last", status_code=303)
    conn.execute("DELETE FROM local_credentials WHERE id=?", (credential_id,))
    conn.commit()
    return RedirectResponse(url="/settings?saved=1", status_code=303)


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/auth/login", status_code=303)
