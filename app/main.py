"""PortfolioManager — FastAPI application entry point."""
from __future__ import annotations

import logging
import os
import secrets
import asyncio
from contextlib import suppress

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .db import _open, get_db, get_setting, run_migrations, set_setting
from .helpers import _AuthRedirect
from .routers import auth, portfolio, imports, accounts, dividends, benchmark, settings, actions, crypto, savings

# ---------------------------------------------------------------------------
# Logging — goes to stderr → visible in journalctl -u portfoliomanager
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger("portfoliomanager")

# ---------------------------------------------------------------------------
# App creation
# ---------------------------------------------------------------------------

app = FastAPI(
    title="PortfolioManager",
    docs_url=None,   # disable in production
    redoc_url=None,
)


@app.middleware("http")
async def browser_security_middleware(request: Request, call_next):
    """Reject cross-origin writes and apply browser-facing security headers."""
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if origin:
            scheme = request.headers.get("x-forwarded-proto", request.url.scheme).split(",", 1)[0].strip()
            expected_origin = f"{scheme}://{request.headers.get('host', '')}"
            if not secrets.compare_digest(origin, expected_origin):
                return PlainTextResponse("Cross-origin request rejected", status_code=403)

    response = await call_next(request)
    response.headers.setdefault("Content-Security-Policy", "default-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; object-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https://img.logo.dev; connect-src 'self'")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
    return response


# ---------------------------------------------------------------------------
# Session middleware (must come before routes)
# ---------------------------------------------------------------------------

def _session_secret() -> str:
    """Return (or generate) the session secret from the database."""
    from pathlib import Path
    from .db import _DB_PATH, _open
    Path(_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = _open()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS _migrations "
        "(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)"
    )
    conn.commit()
    val = get_setting(conn, "session_secret")
    if not val:
        val = secrets.token_hex(32)
        set_setting(conn, "session_secret", val)
        conn.commit()
    conn.close()
    return val


import os as _os
_https_only = _os.getenv("PM_HTTPS_ONLY", "true").lower() != "false"

app.add_middleware(
    SessionMiddleware,
    secret_key=_session_secret(),
    https_only=_https_only,   # set PM_HTTPS_ONLY=false for local dev over HTTP
    same_site="strict",
    session_cookie="pm_session",
    max_age=86400 * 7,  # 7 days
)

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

from pathlib import Path as _Path
_STATIC_DIR = _Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Exception handler: redirect unauthenticated requests to login
# ---------------------------------------------------------------------------

@app.exception_handler(_AuthRedirect)
async def auth_redirect_handler(request: Request, exc: _AuthRedirect):
    return RedirectResponse(url="/auth/login", status_code=303)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup():
    run_migrations()
    from .auth import has_credentials, issue_initial_setup_token
    conn = _open()
    try:
        setup_token = issue_initial_setup_token(conn)
        if setup_token:
            log.warning("No WebAuthn credential exists. Initial setup token: %s", setup_token)
        elif not has_credentials(conn):
            log.warning("No WebAuthn credential exists. Set PM_SETUP_TOKEN to choose a new initial setup token.")
    finally:
        conn.close()
    from .services.refresh_scheduler import scheduler_loop
    app.state.refresh_scheduler_task = asyncio.create_task(scheduler_loop())


@app.on_event("shutdown")
async def shutdown():
    task = getattr(app.state, "refresh_scheduler_task", None)
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(auth.router)
app.include_router(portfolio.router)
app.include_router(imports.router)
app.include_router(accounts.router)
app.include_router(dividends.router)
app.include_router(benchmark.router)
app.include_router(settings.router)
app.include_router(actions.router)
app.include_router(crypto.router)
app.include_router(savings.router)
