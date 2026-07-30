"""Read-only Bitvavo crypto overview."""
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..db import get_db, get_setting, set_setting
from ..helpers import require_auth, templates
from ..services.bitvavo import BitvavoError, crypto_overview, sync_bitvavo
from ..services.credentials import CredentialError, get_bitvavo_credentials, has_bitvavo_credentials

router = APIRouter(prefix="/crypto", tags=["crypto"])


@router.get("", response_class=HTMLResponse)
async def crypto_page(request: Request, conn=Depends(get_db), _=Depends(require_auth)):
    try:
        activity_page = int(request.query_params.get("activity_page", "1"))
    except ValueError:
        activity_page = 1
    data = crypto_overview(conn, activity_page=activity_page)
    return templates.TemplateResponse("crypto.html", {
        "request": request,
        "crypto": data,
        "bitvavo_configured": has_bitvavo_credentials(conn),
        "include_in_dashboard": get_setting(conn, "include_crypto_in_dashboard", "1") != "0",
    })


@router.post("/visibility")
async def set_crypto_visibility(
    include_in_dashboard: int = Form(0),
    conn=Depends(get_db),
    _=Depends(require_auth),
):
    set_setting(conn, "include_crypto_in_dashboard", "1" if include_in_dashboard else "0")
    return RedirectResponse(url="/crypto", status_code=303)


@router.post("/sync")
async def sync_crypto(conn=Depends(get_db), _=Depends(require_auth)):
    try:
        credentials = get_bitvavo_credentials(conn)
        if not credentials:
            return RedirectResponse(url="/accounts?bitvavo_error=missing#crypto-bitvavo", status_code=303)
        result = sync_bitvavo(conn, *credentials)
        return RedirectResponse(url=f"/crypto?synced={result['balances']}", status_code=303)
    except (BitvavoError, CredentialError) as exc:
        return RedirectResponse(url=f"/crypto?error={quote(str(exc)[:180])}", status_code=303)
