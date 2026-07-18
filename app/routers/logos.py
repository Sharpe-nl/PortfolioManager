"""Authenticated local logo-cache endpoint."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, Response

from ..db import get_db
from ..helpers import require_auth
from ..services.logo_cache import LogoFetchError, get_cached_logo

router = APIRouter(prefix="/logos", tags=["logos"])


@router.get("/{mode}")
async def logo(mode: str, value: str = Query(..., max_length=200), conn=Depends(get_db), _=Depends(require_auth)):
    try:
        path = await asyncio.to_thread(get_cached_logo, conn, mode, value)
    except ValueError:
        return Response(status_code=404)
    except LogoFetchError:
        return Response(status_code=502)
    if path is None:
        return Response(status_code=404)
    return FileResponse(
        path,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
