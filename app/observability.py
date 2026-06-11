"""Opik observability shim (D8).

One place for the optional-Opik plumbing so the rest of the codebase never writes
a ``try: import opik`` block. Everything degrades to a clean no-op when Opik is
absent *or* unconfigured (no API key), which is exactly the resilience AC1.8 wants:
"with the key unset or Opik down, every other AC still passes."

The ``@track`` decorator decides at *call* time (not import time) whether to trace,
so configuration can happen in the app lifespan after the modules are imported.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import os
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

try:  # package present?
    import opik
    from opik import opik_context

    _HAS_OPIK = True
except ImportError:  # pragma: no cover - exercised only in opik-less envs
    opik = None
    opik_context = None
    _HAS_OPIK = False

# Flipped True only after a successful configure() with a real key.
OPIK_AVAILABLE = False
_configured = False
_PROJECT = "fastpilot"
_client_instance: Any = None


def opik_client() -> Any:
    """One shared Opik client (constructing one per call makes a fresh HTTP session
    each time). Used for prompt fetch, feedback, and trace updates."""
    global _client_instance
    if _client_instance is None and _HAS_OPIK:
        _client_instance = opik.Opik(project_name=_PROJECT)
    return _client_instance


def configure_opik(api_key: str, workspace: str, project: str) -> bool:
    """Configure Opik once. Returns True if tracing is live.

    No key, no package, or a configure failure → tracing stays off (no-op).
    """
    global OPIK_AVAILABLE, _configured, _PROJECT
    if _configured:
        return OPIK_AVAILABLE
    _configured = True
    _PROJECT = project

    if not (_HAS_OPIK and api_key):
        logger.info("Opik tracing disabled (%s)", "no package" if not _HAS_OPIK else "no API key")
        return False

    try:
        # OPIK_PROJECT_NAME makes every @track trace land in the configured project
        # (opik.configure itself takes no project arg) instead of "Default Project".
        os.environ["OPIK_PROJECT_NAME"] = project
        opik.configure(api_key=api_key, workspace=workspace)
        OPIK_AVAILABLE = True
        logger.info("Opik tracing enabled (workspace=%s, project=%s)", workspace, project)
    except Exception as exc:  # noqa: BLE001 - telemetry must never break startup
        logger.warning("Opik configure failed, tracing disabled: %s", exc)
        OPIK_AVAILABLE = False
    return OPIK_AVAILABLE


def track(name: Optional[str] = None) -> Callable:
    """Decorator: trace this function as an Opik span when tracing is live.

    Pre-wraps once; chooses traced vs raw per call based on ``OPIK_AVAILABLE``.
    Works for both sync and async callables.
    """

    def decorator(fn: Callable) -> Callable:
        traced = opik.track(name=name or fn.__name__)(fn) if _HAS_OPIK else fn

        if asyncio.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def awrapper(*args: Any, **kwargs: Any) -> Any:
                target = traced if OPIK_AVAILABLE else fn
                return await target(*args, **kwargs)

            return awrapper

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            target = traced if OPIK_AVAILABLE else fn
            return target(*args, **kwargs)

        return wrapper

    return decorator


# --- Guarded helpers (all silent no-ops when tracing is off) ---------------
def set_thread_id(thread_id: str) -> None:
    if OPIK_AVAILABLE:
        try:
            opik_context.update_current_trace(thread_id=thread_id)
        except Exception:  # noqa: BLE001
            pass


def current_trace_id() -> Optional[str]:
    if OPIK_AVAILABLE:
        try:
            data = opik_context.get_current_trace_data()
            return data.id if data else None
        except Exception:  # noqa: BLE001
            return None
    return None


def update_current_span(**fields: Any) -> None:
    if OPIK_AVAILABLE:
        try:
            opik_context.update_current_span(**fields)
        except Exception:  # noqa: BLE001
            pass


def link_prompt_to_trace(prompt_obj: Any) -> None:
    if OPIK_AVAILABLE and prompt_obj is not None:
        try:
            opik_context.update_current_trace(prompts=[prompt_obj])
        except Exception:  # noqa: BLE001
            pass


def log_feedback_score(trace_id: str, rating: str, comment: str = "", reason: str = "") -> bool:
    """Attach a user-feedback score to a trace. Returns True on success."""
    if not (OPIK_AVAILABLE and trace_id):
        return False
    try:
        opik_client().log_traces_feedback_scores(
            scores=[
                {
                    "id": trace_id,
                    "name": "user_feedback",
                    "value": 1.0 if rating == "up" else 0.0,
                    "category_name": reason or ("positive" if rating == "up" else "negative"),
                    "reason": comment or None,
                }
            ]
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Opik feedback logging failed: %s", exc)
        return False


def update_trace_output(trace_id: str, output: dict) -> None:
    """Patch a trace's output after streaming completes (so eval rules see the answer).

    No synchronous flush — the background sender ships it, and the lifespan
    ``flush()`` drains on shutdown. A blocking flush here would add up to its
    timeout to the stream's final ``done`` event.
    """
    if not (OPIK_AVAILABLE and trace_id):
        return
    try:
        client = opik_client()
        client.update_trace(trace_id=trace_id, project_name=_PROJECT, output=output)
    except Exception:  # noqa: BLE001
        pass


def flush() -> None:
    if OPIK_AVAILABLE:
        try:
            opik.flush_tracker()
        except Exception:  # noqa: BLE001
            pass
