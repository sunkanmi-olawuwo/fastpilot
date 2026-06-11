"""Opik prompt registry — versioning + hot-swap (D8).

- ``register_prompts()`` at startup: push templates to Opik (auto-versions on change,
  no-op if unchanged).
- ``fetch_prompt()`` at runtime: pull the latest version so an edit in the Opik UI is
  picked up on the next request — no redeploy.

Both gracefully fall back to the hardcoded templates when Opik is unavailable, so the
system always works; Opik adds versioning + hot-swap on top.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

# Import the module (not the flag value): OPIK_AVAILABLE flips to True inside
# configure_opik() at startup, AFTER this module is imported. Reading it through
# the module at call time picks up that change; importing the bool by value would
# freeze the import-time False and disable prompt versioning forever.
from app import observability
from app.prompts.templates import TEMPLATES

logger = logging.getLogger(__name__)

try:
    import opik
except ImportError:  # pragma: no cover
    opik = None

# Short-TTL cache so we don't make a synchronous Opik HTTP call on *every* request
# (live testing showed that fetch dominating per-request latency). Hot-swap still
# works — an edit in the Opik UI is picked up within TTL seconds.
_PROMPT_TTL_S = 60.0
_prompt_cache: dict[str, tuple[float, str, Optional[Any]]] = {}


def reset_prompt_cache() -> None:
    """Clear the prompt cache (tests; or to force an immediate re-fetch)."""
    _prompt_cache.clear()


def _prompt_name(query_type: str) -> str:
    """FACTUAL -> rag-factual, CODE_GENERATION -> rag-code-generation."""
    return f"rag-{query_type.lower().replace('_', '-')}"


def register_prompts() -> None:
    """Register every generation template in Opik's prompt library (idempotent)."""
    if not (observability.OPIK_AVAILABLE and opik is not None):
        logger.debug("Opik unavailable — skipping prompt registration")
        return
    try:
        for query_type, template_text in TEMPLATES.items():
            opik.Prompt(name=_prompt_name(query_type), prompt=template_text)
        logger.info("Registered %d prompts in Opik", len(TEMPLATES))
    except Exception as exc:  # noqa: BLE001 - non-fatal; hardcoded fallback still works
        logger.warning("Opik prompt registration failed (using hardcoded): %s", exc)


def fetch_prompt(query_type: str) -> tuple[str, Optional[Any]]:
    """Return ``(prompt_text, prompt_object)`` — object is for trace linking (or None).

    Served from a 60s in-process cache so only the first request per query-type per
    minute pays the Opik round-trip; the rest are local. Falls back to the hardcoded
    template whenever Opik is unavailable or errors.
    """
    fallback = TEMPLATES.get(query_type, TEMPLATES["FACTUAL"])

    # Gate on observability's authoritative flag — fetch uses observability.opik_client(),
    # not this module's `opik` import, so don't couple to whether *that* import succeeded.
    if not observability.OPIK_AVAILABLE:
        return fallback, None

    cached = _prompt_cache.get(query_type)
    if cached is not None and (time.monotonic() - cached[0]) < _PROMPT_TTL_S:
        return cached[1], cached[2]

    try:
        prompt_obj = observability.opik_client().get_prompt(name=_prompt_name(query_type))
        if prompt_obj is not None:
            _prompt_cache[query_type] = (time.monotonic(), prompt_obj.prompt, prompt_obj)
            return prompt_obj.prompt, prompt_obj
        return fallback, None
    except Exception:  # noqa: BLE001 - non-fatal; use hardcoded
        return fallback, None
