"""Small-module units: the Redis factory, source-label fallthrough, the Playground
rate limiter, the dogfood writer, the service registry, and the Opik shim's active
paths (driven by a fake opik so the otherwise-no-op helpers actually run).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

# Captured at import time — BEFORE the autouse conftest fixtures patch them — so the
# dogfood/observability tests can drive the *real* module functions, not the stubs.
from app import dogfood as _dogfood
from app import observability as _obs

_REAL_APPEND = _dogfood._append
_REAL_CONFIGURE = _obs.configure_opik


# --- redis_client factory -------------------------------------------------
def _settings(**kw):
    base = dict(redis_host="h", redis_port=6380, redis_username="u", redis_password="p", redis_ssl=False)
    base.update(kw)
    return SimpleNamespace(**base)


def test_make_redis_client_propagates_settings():
    from app.redis_client import make_redis_client

    client = make_redis_client(_settings(), decode_responses=True)
    kwargs = client.connection_pool.connection_kwargs
    assert kwargs["host"] == "h"
    assert kwargs["port"] == 6380
    assert kwargs["username"] == "u"
    assert kwargs["password"] == "p"
    assert kwargs["decode_responses"] is True


def test_make_redis_client_blanks_become_none():
    from app.redis_client import make_redis_client

    # Empty username/password must collapse to None (Redis Cloud default-user auth).
    client = make_redis_client(_settings(redis_username="", redis_password=""), decode_responses=False)
    kwargs = client.connection_pool.connection_kwargs
    assert kwargs["username"] is None
    assert kwargs["password"] is None
    assert kwargs["decode_responses"] is False


def test_make_redis_client_tls_uses_ssl_connection():
    from redis.connection import SSLConnection

    from app.redis_client import make_redis_client

    client = make_redis_client(_settings(redis_ssl=True), decode_responses=True)
    assert client.connection_pool.connection_class is SSLConnection


# --- formatting.source_label fallthrough ----------------------------------
def test_source_label_prefers_first_present_key():
    from app.formatting import source_label

    assert source_label({"file_path": "a.md", "title": "ignored"}) == "a.md"
    assert source_label({"title": "Tutorial"}) == "Tutorial"


def test_source_label_falls_through_to_source_then_category():
    from app.formatting import source_label

    assert source_label({"source": "github"}) == "github"
    assert source_label({"category": "docs"}) == "docs"
    assert source_label({}) == "unknown"


# --- rate limiter ---------------------------------------------------------
def test_rate_limiter_in_memory_allows_then_blocks():
    from app.augmentations.rate_limit import RateLimiter

    rl = RateLimiter(per_minute=2)
    assert rl.check("sess") == (True, 0)
    assert rl.check("sess") == (True, 0)
    allowed, retry_after = rl.check("sess")
    assert allowed is False
    assert retry_after >= 1  # tells the caller when to come back


def test_rate_limiter_blank_session_bucketed_as_anon():
    from app.augmentations.rate_limit import RateLimiter

    rl = RateLimiter(per_minute=1)
    assert rl.check("")[0] is True
    assert rl.check("")[0] is False  # same "anon" bucket


def test_rate_limiter_redis_path_counts_and_blocks():
    import fakeredis

    from app.augmentations.rate_limit import RateLimiter

    rl = RateLimiter(redis_client=fakeredis.FakeRedis(decode_responses=True), per_minute=2)
    assert rl.check("s")[0] is True
    assert rl.check("s")[0] is True
    assert rl.check("s")[0] is False  # 3rd in the same 60s bucket


def test_rate_limiter_fails_open_on_redis_error():
    from app.augmentations.rate_limit import RateLimiter

    class _BoomRedis:
        def incr(self, key):
            raise RuntimeError("redis down")

    rl = RateLimiter(redis_client=_BoomRedis(), per_minute=1)
    # Never block on Redis trouble — a friendly rate limit fails open.
    assert rl.check("s") == (True, 0)


# --- dogfood writer -------------------------------------------------------
def test_dogfood_writes_interaction_and_feedback(tmp_path, monkeypatch):
    monkeypatch.setattr(_dogfood, "_append", _REAL_APPEND)  # restore the real writer
    monkeypatch.setattr(_dogfood, "_LOG_DIR", tmp_path)
    monkeypatch.setattr(_dogfood, "_LOG_PATH", tmp_path / "sessions.jsonl")
    monkeypatch.setattr(_dogfood, "_ENABLED", True)

    _dogfood.log_interaction(
        session_id="s",
        msg_id="m1",
        mode="chat",
        query="q",
        answer="a",
        contexts=[{"metadata": {"file_path": "docs/x.md"}, "score": 0.8}],
        cache_hit=True,
        query_type="HOW_TO",
        latency_ms=123.45,
    )
    _dogfood.log_feedback(msg_id="m1", rating="up", comment="great")

    import json

    lines = (tmp_path / "sessions.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
    interaction = json.loads(lines[0])
    assert interaction["type"] == "interaction"
    assert interaction["msg_id"] == "m1"
    assert interaction["cache_hit"] is True
    assert interaction["contexts"] == [{"file_path": "docs/x.md", "score": 0.8}]  # slimmed
    assert interaction["latency_ms"] == 123.5  # rounded to 1dp
    feedback = json.loads(lines[1])
    assert feedback == {**feedback, "type": "feedback", "msg_id": "m1", "rating": "up", "comment": "great"}


def test_dogfood_disabled_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(_dogfood, "_append", _REAL_APPEND)
    monkeypatch.setattr(_dogfood, "_LOG_PATH", tmp_path / "sessions.jsonl")
    monkeypatch.setattr(_dogfood, "_LOG_DIR", tmp_path)
    _dogfood.set_enabled(False)
    try:
        _dogfood.log_interaction(session_id="s", msg_id="m", mode="chat", query="q", answer="a")
        assert not (tmp_path / "sessions.jsonl").exists()
    finally:
        _dogfood.set_enabled(True)  # restore module default for other tests


# --- service registry -----------------------------------------------------
def test_set_and_reset_services_roundtrip():
    from app import services

    services.reset_services()
    sentinel = object()
    services.set_services(rag=sentinel)
    assert services.get_rag_pipeline() is sentinel  # injected singleton returned
    services.set_services(cache=sentinel, conversation=sentinel, router=sentinel)
    assert services.get_semantic_cache() is sentinel
    assert services.get_conversation_service() is sentinel
    assert services.get_query_router() is sentinel
    services.reset_services()
    assert services._rag is None and services._cache is None


def test_set_services_only_replaces_provided():
    from app import services

    services.reset_services()
    a, b = object(), object()
    services.set_services(rag=a, cache=b)
    services.set_services(rag=object())  # cache must be untouched
    assert services.get_semantic_cache() is b
    services.reset_services()


def test_getters_lazily_construct_degraded_singletons():
    """With no Redis reachable in a unit test, the getters build real (degraded)
    singletons instead of raising — and return the same instance on the next call."""
    from app import services

    services.reset_services()
    try:
        cache = services.get_semantic_cache()
        assert cache.available is False  # degraded: no Redis in the hermetic env
        assert services.get_semantic_cache() is cache  # singleton, not rebuilt

        conv = services.get_conversation_service()
        assert conv.is_healthy() is False
        assert services.get_conversation_service() is conv

        router = services.get_query_router()
        assert router is not None
        assert services.get_query_router() is router
    finally:
        services.reset_services()  # don't leak degraded singletons into other tests


# --- dogfood error path ---------------------------------------------------
def test_dogfood_append_swallows_write_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(_dogfood, "_append", _REAL_APPEND)
    monkeypatch.setattr(_dogfood, "_LOG_DIR", tmp_path)
    monkeypatch.setattr(_dogfood, "_LOG_PATH", tmp_path)  # a directory → open('a') raises
    monkeypatch.setattr(_dogfood, "_ENABLED", True)
    # A write failure must never propagate into the request path.
    _dogfood.log_feedback(msg_id="m", rating="up")


# --- observability shim: active (traced) paths ----------------------------
class _FakeOpikContext:
    def __init__(self):
        self.trace_updates: list[dict] = []
        self.span_updates: list[dict] = []

    def update_current_trace(self, **fields):
        self.trace_updates.append(fields)

    def update_current_span(self, **fields):
        self.span_updates.append(fields)

    def get_current_trace_data(self):
        return SimpleNamespace(id="trace_123")


class _FakeOpikClient:
    def __init__(self):
        self.feedback: list = []
        self.outputs: list = []

    def log_traces_feedback_scores(self, scores):
        self.feedback.append(scores)

    def update_trace(self, trace_id, project_name, output):
        self.outputs.append((trace_id, output))


@pytest.fixture
def opik_on(monkeypatch):
    ctx = _FakeOpikContext()
    client = _FakeOpikClient()
    monkeypatch.setattr(_obs, "OPIK_AVAILABLE", True)
    monkeypatch.setattr(_obs, "opik_context", ctx)
    monkeypatch.setattr(_obs, "opik_client", lambda: client)
    return ctx, client


def test_helpers_call_through_when_tracing_on(opik_on):
    ctx, _client = opik_on
    _obs.set_thread_id("sess_42")
    _obs.update_current_span(output={"cache_hit": True})
    _obs.link_prompt_to_trace(object())
    assert {"thread_id": "sess_42"} in ctx.trace_updates
    assert {"output": {"cache_hit": True}} in ctx.span_updates
    assert _obs.current_trace_id() == "trace_123"


def test_link_prompt_to_trace_ignores_none(opik_on):
    ctx, _client = opik_on
    _obs.link_prompt_to_trace(None)  # guard: no prompt → no trace mutation
    assert all("prompts" not in u for u in ctx.trace_updates)


def test_log_feedback_score_up_and_down(opik_on):
    _ctx, client = opik_on
    assert _obs.log_feedback_score("trace_1", "up", comment="nice") is True
    assert _obs.log_feedback_score("trace_2", "down", reason="incorrect") is True
    up = client.feedback[0][0]
    assert up["value"] == 1.0 and up["reason"] == "nice"
    down = client.feedback[1][0]
    assert down["value"] == 0.0 and down["category_name"] == "incorrect"


def test_log_feedback_score_swallows_errors(monkeypatch):
    monkeypatch.setattr(_obs, "OPIK_AVAILABLE", True)

    class _Boom:
        def log_traces_feedback_scores(self, scores):
            raise RuntimeError("opik down")

    monkeypatch.setattr(_obs, "opik_client", lambda: _Boom())
    assert _obs.log_feedback_score("t", "up") is False  # telemetry failure never propagates


def test_update_trace_output_when_on(opik_on):
    _ctx, client = opik_on
    _obs.update_trace_output("trace_9", {"answer": "done"})
    assert client.outputs == [("trace_9", {"answer": "done"})]


def test_flush_when_on(monkeypatch):
    flushed = {"n": 0}
    monkeypatch.setattr(_obs, "OPIK_AVAILABLE", True)
    monkeypatch.setattr(_obs, "opik", SimpleNamespace(flush_tracker=lambda: flushed.__setitem__("n", 1)))
    _obs.flush()
    assert flushed["n"] == 1


def test_configure_opik_success_flips_available(monkeypatch):
    configured = {}

    fake_opik = SimpleNamespace(configure=lambda **kw: configured.update(kw))
    monkeypatch.setattr(_obs, "_HAS_OPIK", True)
    monkeypatch.setattr(_obs, "opik", fake_opik)
    monkeypatch.setattr(_obs, "_configured", False)
    monkeypatch.setattr(_obs, "OPIK_AVAILABLE", False)

    assert _REAL_CONFIGURE("the-key", "ws", "fastpilot") is True
    assert _obs.OPIK_AVAILABLE is True
    assert configured == {"api_key": "the-key", "workspace": "ws"}


def test_configure_opik_no_key_stays_off(monkeypatch):
    monkeypatch.setattr(_obs, "_HAS_OPIK", True)
    monkeypatch.setattr(_obs, "_configured", False)
    monkeypatch.setattr(_obs, "OPIK_AVAILABLE", False)
    assert _REAL_CONFIGURE("", "ws", "proj") is False


def test_configure_opik_handles_failure(monkeypatch):
    def _boom(**kw):
        raise RuntimeError("bad workspace")

    monkeypatch.setattr(_obs, "_HAS_OPIK", True)
    monkeypatch.setattr(_obs, "opik", SimpleNamespace(configure=_boom))
    monkeypatch.setattr(_obs, "_configured", False)
    monkeypatch.setattr(_obs, "OPIK_AVAILABLE", False)
    assert _REAL_CONFIGURE("key", "ws", "proj") is False  # configure crash → tracing stays off


def test_configure_opik_idempotent(monkeypatch):
    monkeypatch.setattr(_obs, "_configured", True)
    monkeypatch.setattr(_obs, "OPIK_AVAILABLE", True)
    # Already configured → returns the cached state without reconfiguring.
    assert _REAL_CONFIGURE("ignored", "ws", "proj") is True


def test_helpers_swallow_opik_runtime_errors(monkeypatch):
    """Every guarded helper must absorb an Opik runtime failure — telemetry trouble
    can never break a request path."""

    class _BoomCtx:
        def update_current_trace(self, **_k):
            raise RuntimeError("opik ctx down")

        def update_current_span(self, **_k):
            raise RuntimeError("opik ctx down")

        def get_current_trace_data(self):
            raise RuntimeError("opik ctx down")

    class _BoomClient:
        def update_trace(self, **_k):
            raise RuntimeError("opik client down")

    def _boom_flush():
        raise RuntimeError("flush down")

    monkeypatch.setattr(_obs, "OPIK_AVAILABLE", True)
    monkeypatch.setattr(_obs, "opik_context", _BoomCtx())
    monkeypatch.setattr(_obs, "opik_client", lambda: _BoomClient())
    monkeypatch.setattr(_obs, "opik", SimpleNamespace(flush_tracker=_boom_flush))

    _obs.set_thread_id("s")  # all of these must be no-throw despite the boom
    _obs.update_current_span(output={"k": "v"})
    _obs.link_prompt_to_trace(object())
    _obs.update_trace_output("trace", {"answer": "x"})
    _obs.flush()
    assert _obs.current_trace_id() is None  # error → None, not a raise


def test_opik_client_is_constructed_once_and_cached(monkeypatch):
    built = {"n": 0}

    class _Opik:
        def __init__(self, project_name=None):
            built["n"] += 1
            self.project_name = project_name

    monkeypatch.setattr(_obs, "_HAS_OPIK", True)
    monkeypatch.setattr(_obs, "opik", SimpleNamespace(Opik=_Opik))
    monkeypatch.setattr(_obs, "_client_instance", None)

    first = _obs.opik_client()
    second = _obs.opik_client()
    assert first is second  # one shared client, not a fresh HTTP session per call
    assert built["n"] == 1
