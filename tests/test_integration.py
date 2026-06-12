"""Real-Redis roundtrips (``-m integration``) — the paths fakeredis can't emulate.

Conversation memory runs on fakeredis in the unit suite, but the semantic cache's
RediSearch HNSW/KNN vector search needs a real redis-stack. These tests exercise the
genuine ``FT.CREATE`` / ``hset`` / ``KNN`` round-trip against the local test container
(``docker compose --profile test up``), and are deselected from the default run.

Bring the container up with ``docker compose --profile test up -d redis-test`` (from
``final-submission/``) — it publishes redis-stack on host port **6380** (6379 is left
free for a local Redis). Override with ``REDIS_TEST_URL`` if yours differs. Skipped
cleanly when no redis-stack is reachable, so a contributor without Docker still gets green.
"""

from __future__ import annotations

import hashlib
import os

import numpy as np
import pytest

pytestmark = pytest.mark.integration

# Default matches the compose `redis-test` service (6380:6379), not a bare local Redis.
_URL = os.getenv("REDIS_TEST_URL", "redis://localhost:6380")


@pytest.fixture(scope="module")
def redis_url() -> str:
    import redis

    client = redis.Redis.from_url(_URL)
    try:
        client.ping()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"redis-stack not reachable at {_URL}: {exc}")
    finally:
        client.close()
    return _URL


# --- Conversation memory on real Redis ------------------------------------
def test_conversation_roundtrip_on_real_redis(redis_url):
    import redis
    from app.services.conversation import ConversationService
    from tests.conftest import FakeChatGenerator

    client = redis.Redis.from_url(redis_url, decode_responses=True)
    conv = ConversationService(redis_client=client, rewriter=FakeChatGenerator())
    session = "itest_conv_" + hashlib.md5(redis_url.encode()).hexdigest()[:8]
    # Clean slate.
    client.delete(f"chat:{session}:messages", f"chat:{session}:meta")

    conv.add_message(session, "user", "How do I add JWT auth?")
    conv.add_message(session, "assistant", "Use OAuth2PasswordBearer [1].")
    history = conv.get_history(session)
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[0]["content"] == "How do I add JWT auth?"

    info = conv.get_session_info(session)
    assert info["total_messages"] == 2
    assert conv.is_healthy() is True
    assert client.ttl(f"chat:{session}:messages") > 0  # sliding TTL applied

    client.delete(f"chat:{session}:messages", f"chat:{session}:meta")
    client.close()


def test_conversation_window_trims_on_real_redis(redis_url):
    import redis
    from app.services.conversation import ConversationService
    from tests.conftest import FakeChatGenerator

    client = redis.Redis.from_url(redis_url, decode_responses=True)
    conv = ConversationService(redis_client=client, rewriter=FakeChatGenerator())
    session = "itest_window_" + hashlib.md5(redis_url.encode()).hexdigest()[:8]
    client.delete(f"chat:{session}:messages", f"chat:{session}:meta")

    for i in range(conv.window_size + 5):
        conv.add_message(session, "user", f"message {i}")
    history = conv.get_history(session)
    assert len(history) == conv.window_size  # LTRIM keeps only the window
    assert history[-1]["content"] == f"message {conv.window_size + 4}"

    client.delete(f"chat:{session}:messages", f"chat:{session}:meta")
    client.close()


# --- Semantic cache KNN on real redis-stack -------------------------------
class _DeterministicEmbedder:
    """Same text → same unit vector (cosine distance 0 → guaranteed hit); different
    text → a different direction (distance well above threshold → miss). No network.

    Each component is a finite value in [-1, 1] derived byte-wise from the SHA-256
    digest — NOT a raw reinterpretation of the bytes as float32, which would yield
    NaN/Inf lanes and poison the cosine distance."""

    def __init__(self, dim: int = 8):
        self.dim = dim

    def embed(self, text: str) -> np.ndarray:
        digest = hashlib.sha256(text.encode()).digest()
        vals = [(digest[i % len(digest)] / 127.5) - 1.0 for i in range(self.dim)]
        vec = np.array(vals, dtype=np.float32)
        norm = float(np.linalg.norm(vec)) or 1.0
        return (vec / norm).astype(np.float32)


def test_semantic_cache_knn_roundtrip(redis_url):
    import redis
    from app.services.semantic_cache import INDEX_NAME, SemanticCache, create_cache_index

    client = redis.Redis.from_url(redis_url, decode_responses=False)  # raw embedding bytes
    # Fresh index at our small test dimension.
    try:
        client.ft(INDEX_NAME).dropindex(delete_documents=True)
    except Exception:  # noqa: BLE001 - absent index is fine
        pass
    assert create_cache_index(client, dimension=8) is True

    cache = SemanticCache(redis_client=client, embedder=_DeterministicEmbedder(dim=8))
    cache.dimension = 8
    cache.threshold = 0.2
    cache.ttl = 60

    query = "How do I validate a request body with Pydantic?"
    assert cache.get(query)[0] is None  # cold miss

    cache.set(query, "Use a Pydantic BaseModel [1].", [{"rank": 1, "content": "x"}], query_type="HOW_TO")
    hit, emb = cache.get(query)
    assert hit is not None  # identical query → KNN distance ~0 → hit
    assert hit["answer"] == "Use a Pydantic BaseModel [1]."
    assert hit["query_type"] == "HOW_TO"
    assert hit["contexts"] == [{"rank": 1, "content": "x"}]
    assert emb is not None

    far, _ = cache.get("Completely unrelated: how do I deploy with Docker Compose?")
    assert far is None  # distant vector → above threshold → miss

    stats = cache.get_stats()
    assert stats["cache_hits"] == 1
    assert stats["num_cached_entries"] >= 1
    assert cache.is_healthy() is True

    client.ft(INDEX_NAME).dropindex(delete_documents=True)
    client.close()
