"""Dogfood interaction logger (plan §11.2).

Appends one JSON line per exchange to ``dogfood/sessions.jsonl`` at the **repo root**
(git-ignored, so the raw log never lands in version control). Feedback is
appended as its own line keyed by ``msg_id`` (append-only is safer than rewriting a
file under concurrency); the "harvest the dogfood log" step joins the two by msg_id.

Best-effort by contract: every function swallows its own errors and never raises into
a request path.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# app/dogfood.py -> app -> repo root
_REPO_ROOT = Path(__file__).resolve().parent.parent
_LOG_DIR = _REPO_ROOT / "dogfood"
_LOG_PATH = _LOG_DIR / "sessions.jsonl"

# Tests disable this (conftest) so unit runs never write to the real log; the app
# can also turn it off via the `dogfood_enabled` setting.
_ENABLED = True


def set_enabled(enabled: bool) -> None:
    """Enable/disable dogfood logging globally (tests + the dogfood_enabled flag)."""
    global _ENABLED
    _ENABLED = enabled


def _append(record: dict) -> None:
    if not _ENABLED:
        return
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        with _LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001 - logging must never break a request
        logger.debug("dogfood append failed: %s", exc)


def log_interaction(
    *,
    session_id: str,
    msg_id: str,
    mode: str,
    query: str,
    answer: str,
    contexts: Optional[list[dict[str, Any]]] = None,
    cache_hit: bool = False,
    query_type: Optional[str] = None,
    standalone_query: Optional[str] = None,
    latency_ms: float = 0.0,
    fallback_used: bool = False,
) -> None:
    """Record one completed exchange. Contexts are slimmed to path + score."""
    slim_contexts = [
        {"file_path": (c.get("metadata") or {}).get("file_path", "unknown"), "score": c.get("score")}
        for c in (contexts or [])
    ]
    _append(
        {
            "type": "interaction",
            "ts": time.time(),
            "session_id": session_id,
            "msg_id": msg_id,
            "mode": mode,
            "query": query,
            "standalone_query": standalone_query,
            "answer": answer,
            "contexts": slim_contexts,
            "cache_hit": cache_hit,
            "query_type": query_type,
            "fallback_used": fallback_used,
            "latency_ms": round(latency_ms, 1),
        }
    )


def log_feedback(*, msg_id: str, rating: str, comment: str = "", reason: str = "") -> None:
    """Record a thumbs rating, joined to its interaction by ``msg_id``."""
    _append(
        {
            "type": "feedback",
            "ts": time.time(),
            "msg_id": msg_id,
            "rating": rating,
            "reason": reason,
            "comment": comment,
        }
    )
