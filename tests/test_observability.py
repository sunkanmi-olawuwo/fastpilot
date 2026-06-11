"""Opik shim no-op behavior (AC1.8) + logging config sanity (AC1.7)."""

from __future__ import annotations

import logging

import pytest


def test_opik_disabled_by_default():
    import app.observability as obs

    # Nothing configured in the test env → tracing must be off.
    assert obs.OPIK_AVAILABLE is False


async def test_track_is_transparent_passthrough_when_off():
    from app.observability import track

    @track(name="sync")
    def add(a, b):
        return a + b

    @track(name="async")
    async def amul(a, b):
        return a * b

    assert add(2, 3) == 5
    assert await amul(2, 4) == 8


def test_helpers_are_safe_noops():
    import app.observability as obs

    # None of these may raise when tracing is off.
    obs.set_thread_id("sess_x")
    obs.update_current_span(output={"k": "v"})
    obs.link_prompt_to_trace(None)
    obs.update_trace_output("", {"answer": "x"})
    obs.flush()
    assert obs.current_trace_id() is None
    assert obs.log_feedback_score("", "up") is False


def test_configure_logging_runs_without_error():
    from app.logging_config import configure_logging

    # Both levels must apply cleanly (called at startup with DEBUG/INFO).
    configure_logging("DEBUG")
    configure_logging("INFO")


def test_summary_line_capturable_and_secret_free(caplog: pytest.LogCaptureFixture):
    # Don't reconfigure logging here — dictConfig would evict caplog's handler.
    logger = logging.getLogger("app.test")
    with caplog.at_level(logging.INFO, logger="app.test"):
        logger.info("query done msg=%s type=%s cache_hit=%s latency_ms=%.0f", "msg_1", "HOW_TO", False, 12)

    assert any("query done" in r.getMessage() for r in caplog.records)
    blob = " ".join(r.getMessage() for r in caplog.records)
    assert "sk-" not in blob and "AIza" not in blob  # no secret-shaped tokens


# --- Prompt registry TTL cache (perf: avoid per-request Opik fetch) -----------
def test_fetch_prompt_caches_within_ttl(monkeypatch):
    """With Opik 'on', fetch_prompt hits Opik once per type then serves from cache."""
    from app import observability
    from app.prompts import registry

    calls = {"n": 0}

    class _Obj:
        prompt = "CACHED TEMPLATE"

    class _Client:
        def get_prompt(self, name):  # noqa: ANN001
            calls["n"] += 1
            return _Obj()

    registry.reset_prompt_cache()
    monkeypatch.setattr(observability, "OPIK_AVAILABLE", True)
    monkeypatch.setattr(observability, "opik_client", lambda: _Client())

    a = registry.fetch_prompt("HOW_TO")
    b = registry.fetch_prompt("HOW_TO")
    assert a[0] == "CACHED TEMPLATE" and b[0] == "CACHED TEMPLATE"
    assert calls["n"] == 1  # second call served from cache, no Opik round-trip
    registry.reset_prompt_cache()
