"""Bilingual (nl/en) UI text.

Each page has its own module (dashboard.py, holdings.py, ...) exporting a
NL dict and an EN dict of {key: string}; this module merges them all into
one lookup table. Keys are dotted and page-prefixed (e.g.
"dashboard.hero.title") so two pages can never collide.

Language is stored in a long-lived cookie (not localStorage) because every
page is server-rendered — the server has to know the language *before* it
renders any text, unlike the dark/light theme toggle which is pure CSS and
can flip client-side after the fact.
"""
from __future__ import annotations

from fastapi import Request

from . import (
    accounts,
    actions,
    auth,
    benchmark,
    common,
    dashboard,
    dividends,
    holdings,
    imports,
    instrument,
    misc,
    settings,
)

COOKIE_NAME = "pm_lang"
DEFAULT_LANG = "nl"
SUPPORTED_LANGS = ("nl", "en")

_MODULES = (
    common, dashboard, holdings, dividends, benchmark, actions,
    accounts, settings, instrument, imports, auth, misc,
)

TRANSLATIONS: dict[str, dict[str, str]] = {
    "nl": {k: v for m in _MODULES for k, v in m.NL.items()},
    "en": {k: v for m in _MODULES for k, v in m.EN.items()},
}


def get_lang(request: Request) -> str:
    lang = request.cookies.get(COOKIE_NAME, DEFAULT_LANG)
    return lang if lang in SUPPORTED_LANGS else DEFAULT_LANG


def t(request: Request, key: str, **kwargs) -> str:
    """Jinja2 global: {{ t(request, 'dashboard.hero.title') }}.

    Falls back nl -> the raw key, so a missing translation shows up as an
    ugly-but-visible key rather than a 500. kwargs are applied via
    str.format for the handful of strings with a dynamic part.
    """
    lang = get_lang(request)
    text = TRANSLATIONS.get(lang, {}).get(key) or TRANSLATIONS["nl"].get(key) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text
