"""Service-layer unit tests: query_router, semantic_cache, conversation (plan §10.2).

Redis services are tested two ways: conversation on **fakeredis** (lists/hashes work),
and the semantic cache against a **stubbed** ``ft().search()`` because fakeredis cannot
emulate RediSearch HNSW/KNN — the real vector path is an ``integration`` test.
"""

from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace

import numpy as np

from tests.conftest import FakeChatGenerator


def _install_fake_genai(monkeypatch, factory):
    """Point the app's lazy ``from haystack_integrations...google_genai import
    GoogleGenAIChatGenerator`` at ``factory``, whether or not the real integration
    package is installed. The curated CI image ships ``haystack-ai`` but not the
    provider integrations (the app only needs them at runtime with real creds), so
    importing the module directly would ModuleNotFoundError there. Registering the
    whole dotted chain in ``sys.modules`` makes the import resolve to our fake; all
    entries are undone on teardown via ``monkeypatch``."""
    chain = (
        "haystack_integrations",
        "haystack_integrations.components",
        "haystack_integrations.components.generators",
        "haystack_integrations.components.generators.google_genai",
    )
    for name in chain:
        if name not in sys.modules:
            monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setattr(sys.modules[chain[-1]], "GoogleGenAIChatGenerator", factory, raising=False)


# --- Query router ---------------------------------------------------------
async def test_router_classifies_from_llm_json():
    from app.services.query_router import QueryRouter

    router = QueryRouter(llm=FakeChatGenerator(text='{"category": "TROUBLESHOOTING", "confidence": 0.9}'))
    result = await router.classify("Why am I getting a 422?")
    assert result["category"] == "TROUBLESHOOTING"
    assert result["confidence"] == 0.9


async def test_router_defaults_on_bad_json():
    from app.services.query_router import QueryRouter

    router = QueryRouter(llm=FakeChatGenerator(text="not json at all"))
    result = await router.classify("anything")
    # Unparseable JSON → safe default category (confidence is the template default).
    assert result["category"] == "FACTUAL"


def test_router_build_prompt_formats_citations():
    from haystack import Document

    from app.services.query_router import QueryRouter

    router = QueryRouter(llm=FakeChatGenerator())
    contexts = [Document(content="OAuth2PasswordBearer ...", meta={"file_path": "a.md", "category": "docs"})]
    messages = router.build_prompt("How do I add auth?", contexts, "HOW_TO")
    user_text = messages[1].text
    assert "[1] (source: a.md, type: docs)" in user_text
    assert "QUESTION: How do I add auth?" in user_text


# --- Conversation (fakeredis) ---------------------------------------------
def _conv(rewriter=None):
    import fakeredis

    from app.services.conversation import ConversationService

    return ConversationService(
        redis_client=fakeredis.FakeRedis(decode_responses=True),
        rewriter=rewriter or FakeChatGenerator(),
    )


async def test_first_turn_skips_rewrite():
    rewriter = FakeChatGenerator()
    conv = _conv(rewriter)
    result = await conv.rewrite_if_needed("What is Depends?", "sess_a")
    assert result["is_follow_up"] is False
    assert result["standalone_query"] == "What is Depends?"
    assert rewriter.calls == []  # LLM never touched on the first turn


async def test_followup_triggers_rewrite():
    rewriter = FakeChatGenerator(text="How do I make the path parameter optional?")
    conv = _conv(rewriter)
    conv.add_message("sess_b", "user", "How do I declare a path parameter?")
    conv.add_message("sess_b", "assistant", "Use a typed function argument.")
    result = await conv.rewrite_if_needed("How do I make it optional?", "sess_b")
    assert result["is_follow_up"] is True
    assert result["standalone_query"] == "How do I make the path parameter optional?"
    assert len(rewriter.calls) == 1


def test_window_trims_to_size():
    conv = _conv()
    for i in range(15):
        conv.add_message("sess_c", "user", f"message {i}")
    history = conv.get_history("sess_c")
    assert len(history) == conv.window_size  # 10
    assert history[-1]["content"] == "message 14"


def test_conversation_in_memory_fallback():
    conv = _conv()
    conv.redis = None  # simulate Redis down → in-memory path
    mid = conv.add_message("sess_d", "user", "hi")
    assert mid.startswith("msg_")
    assert conv.get_history("sess_d")[0]["content"] == "hi"
    assert conv.is_healthy() is False


# --- Semantic cache (stubbed RediSearch) ----------------------------------
class _StubEmbedder:
    def embed(self, text: str) -> np.ndarray:
        return np.zeros(8, dtype=np.float32)


class _Doc:
    def __init__(self, distance):
        self.id = "cache:query:abc"
        self.query = "How do I add JWT auth?"
        self.answer = "Use OAuth2PasswordBearer [1]."
        self.timestamp = "0"
        self.distance = str(distance)


class _Result:
    def __init__(self, docs):
        self.docs = docs
        self.total = len(docs)


class _StubFt:
    def __init__(self, result):
        self._result = result

    def search(self, query, query_params=None):
        return self._result

    def info(self):
        return {"num_docs": 1}


class _StubRedis:
    def __init__(self, result, contexts):
        self._ft = _StubFt(result)
        self._contexts = contexts

    def ft(self, name):
        return self._ft

    def hget(self, key, field):
        return json.dumps(self._contexts)

    def ping(self):
        return True


def _cache(result, contexts=None):
    from app.services.semantic_cache import SemanticCache

    return SemanticCache(
        redis_client=_StubRedis(result, contexts or [{"rank": 1}]),
        embedder=_StubEmbedder(),
    )


def test_cache_hit_below_threshold():
    cache = _cache(_Result([_Doc(distance=0.02)]))
    hit, emb = cache.get("How do I add JWT auth?")
    assert hit is not None
    assert hit["answer"] == "Use OAuth2PasswordBearer [1]."
    assert hit["distance"] == 0.02
    assert emb is not None  # embedding returned for reuse, even on a hit


def test_cache_miss_above_threshold():
    cache = _cache(_Result([_Doc(distance=0.5)]))
    hit, emb = cache.get("Totally unrelated question")
    assert hit is None
    assert emb is not None  # miss still returns the embedding (reused by retrieve/set)


def test_cache_miss_when_empty():
    cache = _cache(_Result([]))
    assert cache.get("anything")[0] is None


def test_cache_noop_when_unavailable():
    from app.services.semantic_cache import SemanticCache

    cache = SemanticCache.__new__(SemanticCache)
    cache.available = False
    cache._hits = cache._misses = 0
    assert cache.get("x") == (None, None)
    cache.set("x", "y", [])  # must not raise
    assert cache.is_healthy() is False


def test_cache_get_blank_query_misses_without_embedding():
    cache = _cache(_Result([]))
    assert cache.get("   ") == (None, None)  # empty/whitespace short-circuits, no embed call


def test_cache_lookup_error_returns_none_and_counts_miss():
    from app.services.semantic_cache import SemanticCache

    class _BoomEmbedder:
        def embed(self, text):
            raise RuntimeError("voyage down")

    cache = SemanticCache(redis_client=_StubRedis(_Result([]), []), embedder=_BoomEmbedder())
    hit, emb = cache.get("anything")
    assert hit is None and emb is None  # embed failure is non-fatal
    assert cache.get_stats()["cache_misses"] == 1


def test_cache_set_writes_hash_and_ttl():
    import fakeredis

    fake = fakeredis.FakeRedis()  # bytes mode — set() stores raw embedding bytes

    cache = _cache(_Result([]))
    cache.redis = fake
    cache.ttl = 99
    cache.embedder = _StubEmbedder()
    cache.set("How do I add JWT auth?", "Use OAuth2 [1].", [{"rank": 1}], query_type="HOW_TO")

    keys = fake.keys("cache:query:*")
    assert len(keys) == 1
    stored = fake.hgetall(keys[0])
    assert stored[b"answer"] == b"Use OAuth2 [1]."
    assert stored[b"query_type"] == b"HOW_TO"
    assert fake.ttl(keys[0]) > 0  # TTL applied


def test_cache_get_stats_reports_hit_rate_and_count():
    cache = _cache(_Result([_Doc(distance=0.02)]))
    cache.get("How do I add JWT auth?")  # 1 hit
    cache.get("How do I add JWT auth?")  # 1 hit
    stats = cache.get_stats()
    assert stats["cache_hits"] == 2
    assert stats["total_queries"] == 2
    assert stats["hit_rate_percent"] == 100.0
    assert stats["num_cached_entries"] == 1  # from the stub ft().info()
    assert stats["available"] is True


def test_create_cache_index_creates_when_absent():
    import redis as _redis

    from app.services.semantic_cache import INDEX_NAME, create_cache_index

    created = {}

    class _Ft:
        def info(self):
            raise _redis.exceptions.ResponseError("no such index")

        def create_index(self, schema, definition=None):
            created["schema"] = schema
            created["definition"] = definition

    class _Client:
        def ft(self, name):
            assert name == INDEX_NAME
            return _Ft()

    assert create_cache_index(_Client(), dimension=2048) is True
    assert created["schema"]  # an HNSW schema was pushed


def test_create_cache_index_idempotent_when_present():
    from app.services.semantic_cache import create_cache_index

    class _Ft:
        def info(self):
            return {"attributes": []}  # exists → no-op

    class _Client:
        def ft(self, name):
            return _Ft()

    assert create_cache_index(_Client(), dimension=2048) is False


def test_create_cache_index_reraises_unexpected_response_error():
    import pytest
    import redis as _redis

    from app.services.semantic_cache import create_cache_index

    class _Ft:
        def info(self):
            raise _redis.exceptions.ResponseError("WRONGTYPE some other failure")

    class _Client:
        def ft(self, name):
            return _Ft()

    with pytest.raises(_redis.exceptions.ResponseError):
        create_cache_index(_Client(), dimension=2048)


# --- Conversation degradation + session info -------------------------------
def test_conversation_demotes_on_runtime_redis_error():
    conv = _conv()

    class _BoomRedis:
        def lrange(self, *a):
            raise RuntimeError("connection reset")

    conv.redis = _BoomRedis()
    # A runtime Redis failure must degrade to in-memory, never raise.
    assert conv.get_history("sess_x") == []
    assert conv.degraded is True
    assert conv.redis is None
    assert conv.is_healthy() is False


def test_conversation_add_message_demotes_then_uses_memory():
    conv = _conv()

    class _BoomRedis:
        def pipeline(self):
            raise RuntimeError("down")

    conv.redis = _BoomRedis()
    mid = conv.add_message("sess_y", "user", "hi")
    assert mid.startswith("msg_")
    assert conv.get_history("sess_y")[0]["content"] == "hi"  # served from memory after demote


def test_conversation_session_info_from_redis_and_memory():
    conv = _conv()
    conv.add_message("sess_z", "user", "first")
    conv.add_message("sess_z", "assistant", "reply")
    info = conv.get_session_info("sess_z")
    assert info["session_id"] == "sess_z"
    assert info["total_messages"] == 2
    assert conv.get_session_info("never-seen") is None


def test_conversation_session_info_memory_path():
    conv = _conv()
    conv.redis = None  # in-memory only
    conv.add_message("mem_s", "user", "hi")
    info = conv.get_session_info("mem_s")
    assert info["session_id"] == "mem_s"
    assert info["total_messages"] == 1


async def test_rewrite_falls_back_to_original_on_rewriter_error():
    class _BoomRewriter:
        def run(self, messages=None, **_kw):
            raise RuntimeError("gemini 500")

    conv = _conv(rewriter=_BoomRewriter())
    conv.add_message("sess_r", "user", "earlier turn")
    result = await conv.rewrite_if_needed("a follow-up", "sess_r")
    assert result["is_follow_up"] is True
    assert result["standalone_query"] == "a follow-up"  # rewrite failed → original used


async def test_rewrite_passes_through_without_rewriter():
    import fakeredis

    from app.services.conversation import ConversationService

    conv = ConversationService(redis_client=fakeredis.FakeRedis(decode_responses=True))
    conv._google_key = ""  # force _get_rewriter() down the no-LLM branch → returns None
    conv._rewriter_built = False
    conv.add_message("sess_n", "user", "earlier")
    result = await conv.rewrite_if_needed("next question", "sess_n")
    assert result["is_follow_up"] is True
    assert result["standalone_query"] == "next question"  # no LLM → passes through unrewritten


# --- Query router default paths -------------------------------------------
async def test_router_classify_defaults_when_no_llm():
    from app.services.query_router import QueryRouter

    router = QueryRouter(llm=None)
    router._llm_built = True  # _get_llm returns the injected None
    result = await router.classify("anything")
    assert result == {"category": "FACTUAL", "confidence": 0.0}


def test_router_is_healthy_reflects_llm_presence():
    from app.services.query_router import QueryRouter

    healthy = QueryRouter(llm=FakeChatGenerator())
    assert healthy.is_healthy() is True
    down = QueryRouter(llm=None)
    down._llm_built = True
    assert down.is_healthy() is False


async def test_router_classify_unknown_category_falls_back():
    from app.services.query_router import QueryRouter

    router = QueryRouter(llm=FakeChatGenerator(text='{"category": "NONSENSE", "confidence": 0.9}'))
    result = await router.classify("q")
    assert result == {"category": "FACTUAL", "confidence": 0.0}  # not in QUERY_TYPES → default


async def test_router_classify_parses_fenced_json():
    from app.services.query_router import QueryRouter

    fenced = '```json\n{"category": "CODE_GENERATION", "confidence": 0.8}\n```'
    router = QueryRouter(llm=FakeChatGenerator(text=fenced))
    result = await router.classify("write me an endpoint")
    assert result["category"] == "CODE_GENERATION"


async def test_router_classify_extracts_json_from_noise():
    from app.services.query_router import QueryRouter

    noisy = 'Sure! {"category": "HOW_TO", "confidence": 0.7} hope that helps'
    router = QueryRouter(llm=FakeChatGenerator(text=noisy))
    result = await router.classify("how do I do x")
    assert result["category"] == "HOW_TO"  # braces extracted from surrounding prose


async def test_router_classify_defaults_on_llm_exception():
    from app.services.query_router import QueryRouter

    class _BoomLLM:
        def run(self, messages=None, **_kw):
            raise RuntimeError("gemini 503")

    router = QueryRouter(llm=_BoomLLM())
    result = await router.classify("q")
    assert result == {"category": "FACTUAL", "confidence": 0.0}  # any failure → safe default


async def test_router_classify_handles_unparseable_braces():
    from app.services.query_router import QueryRouter

    # Contains braces but the slice between them still isn't valid JSON → safe default.
    router = QueryRouter(llm=FakeChatGenerator(text="here you go {category: HOW_TO, no quotes} done"))
    result = await router.classify("q")
    assert result["category"] == "FACTUAL"


def test_router_build_prompt_handles_empty_contexts():
    from app.services.query_router import QueryRouter

    router = QueryRouter(llm=FakeChatGenerator())
    messages = router.build_prompt("question?", [], "FACTUAL")
    assert "(No relevant context found.)" in messages[1].text


def test_router_get_llm_builds_from_key(monkeypatch):
    from app.services.query_router import QueryRouter

    _install_fake_genai(monkeypatch, lambda model: SimpleNamespace(model=model))
    router = QueryRouter()  # no llm injected → built lazily
    router._google_key = "fake-key"
    router._llm_built = False
    llm = router._get_llm()
    assert llm is not None and llm.model == router._model


def test_router_get_llm_none_without_key():
    from app.services.query_router import QueryRouter

    router = QueryRouter()
    router._google_key = ""  # no key → classifier disabled, no LLM built
    router._llm_built = False
    assert router._get_llm() is None


def test_router_get_llm_handles_build_failure(monkeypatch):
    from app.services.query_router import QueryRouter

    def _boom(model):
        raise RuntimeError("missing GOOGLE_API_KEY")

    _install_fake_genai(monkeypatch, _boom)
    router = QueryRouter()
    router._google_key = "fake-key"
    router._llm_built = False
    assert router._get_llm() is None  # construction failure degrades to no classifier


# --- Conversation health + cache dim-mismatch ------------------------------
def test_conversation_is_healthy_false_when_ping_raises():
    conv = _conv()

    class _PingBoom:
        def ping(self):
            raise RuntimeError("connection refused")

    conv.redis = _PingBoom()
    assert conv.is_healthy() is False


def test_create_cache_index_warns_on_dim_mismatch(caplog):
    import logging

    from app.services.semantic_cache import create_cache_index

    class _Ft:
        def info(self):
            # Existing index built at DIM=1024; config expects 2048 → silent-miss warning.
            return {"attributes": [["identifier", "embedding", "type", "VECTOR", "dim", "1024"]]}

    class _Client:
        def ft(self, name):
            return _Ft()

    with caplog.at_level(logging.ERROR):
        assert create_cache_index(_Client(), dimension=2048) is False
    assert any("DIM" in r.getMessage() for r in caplog.records)


def test_cache_set_write_error_is_swallowed():
    cache = _cache(_Result([]))

    class _BoomRedis:
        def hset(self, *a, **k):
            raise RuntimeError("redis write failed")

    cache.redis = _BoomRedis()
    cache.embedder = _StubEmbedder()
    cache.set("q", "a", [{"rank": 1}])  # a cache write failure must never propagate


def test_cache_is_healthy_pings_redis():
    cache = _cache(_Result([]))  # _StubRedis.ping returns True
    assert cache.is_healthy() is True


def test_cache_is_healthy_false_when_ping_raises():
    cache = _cache(_Result([]))

    class _PingBoom:
        def ping(self):
            raise RuntimeError("redis gone")

    cache.redis = _PingBoom()
    assert cache.is_healthy() is False


# --- Conversation rewriter build + session-info degradation ----------------
def test_conversation_builds_rewriter_from_key(monkeypatch):
    import fakeredis

    from app.services.conversation import ConversationService

    _install_fake_genai(monkeypatch, lambda model: SimpleNamespace(model=model))
    conv = ConversationService(redis_client=fakeredis.FakeRedis(decode_responses=True))
    conv._google_key = "fake-key"
    conv._rewriter_built = False
    rewriter = conv._get_rewriter()
    assert rewriter is not None and rewriter.model == conv._model


def test_conversation_rewriter_build_failure_degrades(monkeypatch):
    import fakeredis

    from app.services.conversation import ConversationService

    def _boom(model):
        raise RuntimeError("no GOOGLE_API_KEY")

    _install_fake_genai(monkeypatch, _boom)
    conv = ConversationService(redis_client=fakeredis.FakeRedis(decode_responses=True))
    conv._google_key = "fake-key"
    conv._rewriter_built = False
    assert conv._get_rewriter() is None  # build failure → no rewriter (follow-ups pass through)


def test_conversation_session_info_demotes_on_error():
    conv = _conv()

    class _BoomRedis:
        def hgetall(self, *a):
            raise RuntimeError("redis down")

    conv.redis = _BoomRedis()
    # A runtime failure during session-info read degrades to in-memory (None here), no 5xx.
    assert conv.get_session_info("sess_x") is None
    assert conv.degraded is True
