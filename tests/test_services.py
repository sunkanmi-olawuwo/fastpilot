"""Service-layer unit tests: query_router, semantic_cache, conversation (plan §10.2).

Redis services are tested two ways: conversation on **fakeredis** (lists/hashes work),
and the semantic cache against a **stubbed** ``ft().search()`` because fakeredis cannot
emulate RediSearch HNSW/KNN — the real vector path is an ``integration`` test.
"""

from __future__ import annotations

import json

import numpy as np
from tests.conftest import FakeChatGenerator


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
    from app.services.query_router import QueryRouter
    from haystack import Document

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
