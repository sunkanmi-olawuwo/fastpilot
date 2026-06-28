"""Small presentation helpers shared by the API layer and the prompt builder."""

from __future__ import annotations

import re

# The corpus encodes provenance in ``file_path`` as ``<origin>::<rest>`` — e.g.
# ``official_docs::advanced/security/oauth2-scopes/index.md`` or ``github_issue::2603``
# (see scripts/07_reindex_production.py). These map back to canonical public URLs.
_DOCS_BASE = "https://fastapi.tiangolo.com/"
_GH_BASE = "https://github.com/fastapi/fastapi"

# Acronyms that should not be naively title-cased ("oauth2" → "OAuth2", not "Oauth2").
_ACRONYMS = {
    "oauth2": "OAuth2", "api": "API", "apirouter": "APIRouter", "openapi": "OpenAPI",
    "cors": "CORS", "jwt": "JWT", "sql": "SQL", "http": "HTTP", "html": "HTML",
    "url": "URL", "uuid": "UUID", "wsgi": "WSGI", "asgi": "ASGI", "id": "ID", "ssl": "SSL",
}


def source_label(meta: dict) -> str:
    """Best available human source for a chunk. Collections vary in which key
    holds the filename (file_path / file / title / source_id) — fall through them,
    then to the broad source/category, so the sources panel is never blank."""
    for key in ("file_path", "file", "title", "source_id", "name"):
        value = meta.get(key)
        if value:
            return str(value)
    return str(meta.get("source") or meta.get("category") or "unknown")


def _pretty_word(word: str) -> str:
    return _ACRONYMS.get(word.lower(), word[:1].upper() + word[1:])


def _prettify(segment: str) -> str:
    """'oauth2-scopes' → 'OAuth2 Scopes'."""
    return " ".join(_pretty_word(w) for w in re.split(r"[-_\s]+", segment) if w)


def source_title(meta: dict) -> str:
    """Human-readable title for a chunk's source, derived from the raw ``file_path``
    label so the sources panel shows ``Advanced › Security › OAuth2 Scopes`` or
    ``GitHub Issue #2603`` instead of ``official_docs::.../index.md``. Falls back to
    the raw label when the path isn't in the ``origin::rest`` shape."""
    raw = source_label(meta)
    origin, sep, rest = raw.partition("::")
    if not sep:
        return raw
    if origin == "github_issue":
        return f"GitHub Issue #{rest}"
    if origin == "github_discussion":
        return f"GitHub Discussion #{rest}"
    path = re.sub(r"\.md$", "", re.sub(r"/?index\.md$", "", rest))
    segs = [s for s in path.split("/") if s]
    if not segs:
        return _prettify(origin)
    return " › ".join(_prettify(s) for s in segs[-3:])  # last 3 keep it short


def source_url(meta: dict) -> str:
    """Best-effort canonical public URL for a chunk's source (``''`` if unknown),
    so the sources panel can link out to the docs / GitHub thread it grounded on."""
    raw = source_label(meta)
    origin, sep, rest = raw.partition("::")
    if not sep:
        return ""
    if origin == "github_issue":
        return f"{_GH_BASE}/issues/{rest}"
    if origin == "github_discussion":
        return f"{_GH_BASE}/discussions/{rest}"
    if origin == "official_docs":
        path = re.sub(r"\.md$", "/", re.sub(r"/?index\.md$", "/", rest))
        return _DOCS_BASE + path.lstrip("/")
    return ""
