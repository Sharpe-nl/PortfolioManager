"""Shared FastAPI helpers: template engine, auth dependency, Jinja2 filters."""
from __future__ import annotations

import json
import os
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from fastapi import Depends, Request
from fastapi.templating import Jinja2Templates

from .i18n import get_lang as _get_lang
from .i18n import t as _t

_TEMPLATE_DIR = Path(__file__).parent / "templates"


class PortfolioTemplates(Jinja2Templates):
    """Keep existing server-rendered routes compatible with Starlette 1.x.

    Starlette 1.x changed ``TemplateResponse`` to receive ``Request`` first.
    The application deliberately keeps its established ``name, context`` route
    calls and translates them at this single boundary.
    """

    def TemplateResponse(self, request_or_name, name_or_context=None, context=None,
                         status_code: int = 200, headers=None, media_type=None, background=None):
        if isinstance(request_or_name, Request):
            return super().TemplateResponse(
                request_or_name, name_or_context, context, status_code,
                headers, media_type, background,
            )
        legacy_context = name_or_context or {}
        request = legacy_context.get("request")
        if request is None:
            raise ValueError("Template context requires a request")
        return super().TemplateResponse(
            request, request_or_name, legacy_context, status_code,
            headers, media_type, background,
        )


templates = PortfolioTemplates(directory=str(_TEMPLATE_DIR))


def lan_mode_enabled() -> bool:
    """Whether the explicit, HTTP-only home-network mode is active."""
    return (
        os.getenv("PM_LAN_MODE", "").lower() in {"1", "true", "yes"}
        and os.getenv("PM_HTTPS_ONLY", "true").lower() == "false"
    )


templates.env.globals["lan_mode"] = lan_mode_enabled


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

class _AuthRedirect(Exception):
    pass


def require_auth(request: Request) -> None:
    """FastAPI dependency: raise _AuthRedirect if the session is not authenticated."""
    if not request.session.get("authenticated"):
        raise _AuthRedirect()


def optional_account_id(account: str | None = None) -> int | None:
    """FastAPI dependency: parse an `?account=` query param as int | None.

    An <select name="account"><option value="">Alle accounts</option>...
    submits an empty string for "all accounts" — declaring the route param
    directly as `int | None` makes FastAPI/Pydantic reject that empty string
    with a 422 instead of treating it as "no filter". Route handlers should
    use `account: int | None = Depends(optional_account_id)` instead.
    """
    if not account:
        return None
    try:
        return int(account)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Jinja2 filters (Dutch locale formatting)
# ---------------------------------------------------------------------------

def _format_eur(value: Any, show_symbol: bool = True) -> str:
    """Format a Decimal/float/str as Dutch currency: € 1.234,56"""
    if value is None:
        return "—"
    try:
        d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError):
        return str(value)
    negative = d < 0
    d = abs(d)
    int_part = int(d)
    frac = int(round(float(d - int_part) * 100))
    # Format integer part with period as thousands separator
    s = str(int_part)
    parts = []
    while len(s) > 3:
        parts.append(s[-3:])
        s = s[:-3]
    parts.append(s)
    int_str = ".".join(reversed(parts))
    result = f"{int_str},{frac:02d}"
    if negative:
        result = f"-{result}"
    if show_symbol:
        result = f"\u20ac\u00a0{result}"
    return result


def _format_pct(value: Any, sign: bool = True) -> str:
    """Format as Dutch percentage: +12,34% or -5,67%"""
    if value is None:
        return "—"
    try:
        d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError):
        return str(value)
    s = str(abs(d)).replace(".", ",")
    prefix = ("+" if d >= 0 else "-") if sign else ("-" if d < 0 else "")
    return f"{prefix}{s}%"


def _format_qty(value: Any) -> str:
    """Format quantity: strip trailing zeros after decimal, Dutch comma, no scientific notation."""
    if value is None:
        return "—"
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError):
        return str(value)
    # f"{d:f}" always produces fixed-point notation (no scientific notation)
    s = f"{d:f}"
    # Only strip trailing zeros if there is a decimal point
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s.replace(".", ",")


def _pl_class(value: Any) -> str:
    """Return CSS class for P/L colouring."""
    try:
        d = Decimal(str(value))
        if d > 0:
            return "pl-positive"
        if d < 0:
            return "pl-negative"
    except Exception:
        pass
    return ""


from markupsafe import Markup

class _DecimalEncoder(json.JSONEncoder):
    """JSON encoder that converts Decimal → float so templates can use | tojson."""
    def default(self, o: Any) -> Any:
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


def _tojson(value: Any, indent: int | None = None) -> Markup:
    """Jinja2 filter: serialize to JSON, converting Decimal to float.

    Returns Markup so Jinja2 does NOT HTML-escape the output — raw JSON must
    be inserted verbatim into <script> blocks, not as &quot; entities.
    Also escapes </script> to prevent injection.
    """
    result = json.dumps(value, cls=_DecimalEncoder, indent=indent, ensure_ascii=False)
    result = result.replace("</", "<\\/")   # prevent </script> injection
    return Markup(result)


def _fromjson(value: str) -> Any:
    """Jinja2 filter: deserialize JSON string to Python object."""
    try:
        return json.loads(value) if value else {}
    except Exception:
        return {}


# Register filters
templates.env.filters["eur"]     = _format_eur
templates.env.filters["pct"]     = _format_pct
templates.env.filters["qty"]     = _format_qty
templates.env.filters["pl_class"] = _pl_class
templates.env.filters["tojson"]  = _tojson  # override Jinja2 default
templates.env.filters["fromjson"] = _fromjson

# Cache-busting version for shared CSS and JavaScript.
def _static_ver() -> str:
    try:
        static_dir = Path(__file__).parent / "static"
        mtime = max(
            (static_dir / "style.css").stat().st_mtime,
            (static_dir / "app.js").stat().st_mtime,
        )
        return str(int(mtime))
    except Exception:
        return "1"

templates.env.globals["sv"] = _static_ver()


templates.env.globals["t"] = _t
templates.env.globals["get_lang"] = _get_lang
