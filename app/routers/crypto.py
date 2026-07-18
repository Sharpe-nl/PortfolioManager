"""Crypto overview placeholder."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from ..helpers import require_auth, templates

router = APIRouter(prefix="/crypto", tags=["crypto"])


@router.get("", response_class=HTMLResponse)
async def crypto_overview(request: Request, _=Depends(require_auth)):
    return templates.TemplateResponse("crypto.html", {"request": request})
