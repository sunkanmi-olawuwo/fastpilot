"""Semantic cache — Redis HNSW vector search for sub-50ms repeated-query answers.

Stores query→answer→contexts triples keyed by an MD5 of the query; looks up by
cosine distance over Voyage embeddings (same model as retrieval). Graceful
degradation (D4 / AC1.5): if Redis is unreachable or the Search module is missing,
the cache goes to a **no-op** mode — ``get`` always misses, ``set`` does nothing,
``is_healthy`` is False — and the rest of the system keeps working.

Index name + prefix are shared with ``scripts/03_setup_redis.py`` via
``create_cache_index`` so the pre-flight script and the service never drift.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Optional

import numpy as np
import redis
from redis.commands.search.field import NumericField, TextField, VectorField
from redis.commands.search.index_definition import IndexDefinition, IndexType
from redis.commands.search.query import Query

from app.config import get_settings
from app.observability import track, update_current_span

logger = logging.getLogger(__name__)

INDEX_NAME = "fastpilot_cache_idx"
KEY_PREFIX = "cache:query:"


def _warn_on_dim_mismatch(info: Any, expected_dim: int) -> None:
    """An existing index built at a different DIM silently breaks every KNN search
    (stored vectors don't match), degrading the cache to a permanent 0% hit rate
    that /health still reports green. Surface it loudly instead."""
    try:
        attrs = info.get("attributes") or info.get(b"attributes") or []
        for attr in attrs:
            flat = [x.decode() if isinstance(x, bytes) else str(x) for x in attr]
            if "embedding" in flat and "dim" in [s.lower() for s in flat]:
                i = [s.lower() for s in flat].index("dim")
                actual = int(flat[i + 1])
                if actual != expected_dim:
                    logger.error(
                        "Cache index '%s' has DIM=%d but config expects %d — KNN will "
                        "silently miss. Drop the index (FT.DROPINDEX) and re-run 03_setup_redis.py.",
                        INDEX_NAME,
                        actual,
                        expected_dim,
                    )
                return
    except Exception:  # noqa: BLE001 - validation is best-effort, never fatal
        pass


def create_cache_index(client: "redis.Redis", *, dimension: int) -> bool:
    """Create the HNSW cache index if absent. Returns True if created, False if it existed.

    Shared by the service and ``scripts/03_setup_redis.py`` to prevent schema drift.
    """
    try:
        info = client.ft(INDEX_NAME).info()
        _warn_on_dim_mismatch(info, dimension)
        return False
    except redis.exceptions.ResponseError as exc:
        if "no such index" not in str(exc).lower() and "unknown index" not in str(exc).lower():
            raise

    schema = (
        TextField("query"),
        TextField("answer"),
        NumericField("timestamp"),
        VectorField(
            "embedding",
            "HNSW",
            {
                "TYPE": "FLOAT32",
                "DIM": dimension,
                "DISTANCE_METRIC": "COSINE",
                "INITIAL_CAP": 1000,
                "M": 40,
                "EF_CONSTRUCTION": 200,
            },
        ),
    )
    client.ft(INDEX_NAME).create_index(
        schema, definition=IndexDefinition(prefix=[KEY_PREFIX], index_type=IndexType.HASH)
    )
    return True


class _CacheEmbedder:
    """Voyage embedder for query↔query similarity (same model as retrieval)."""

    def __init__(self, model: str, dimension: int):
        import voyageai

        self.client = voyageai.Client()
        self.model = model
        self.dimension = dimension

    def embed(self, text: str) -> np.ndarray:
        result = self.client.embed([text], model=self.model, output_dimension=self.dimension)
        return np.array(result.embeddings[0], dtype=np.float32)


class SemanticCache:
    """Redis HNSW semantic cache with no-op degradation."""

    def __init__(self, *, redis_client: Optional["redis.Redis"] = None, embedder: Any = None):
        s = get_settings()
        self.threshold = s.cache_distance_threshold
        self.ttl = s.cache_ttl
        self.dimension = s.voyage_dimension
        self._hits = 0
        self._misses = 0
        self.available = False
        self.redis = None
        self.embedder = None

        # Injected mode (tests): trust the provided client/embedder, skip index creation.
        if redis_client is not None:
            self.redis = redis_client
            self.embedder = embedder
            self.available = True
            return

        try:
            from app.redis_client import make_redis_client

            self.redis = make_redis_client(s, decode_responses=False)  # raw embedding bytes
            self.redis.ping()
            create_cache_index(self.redis, dimension=self.dimension)
            self.embedder = embedder or _CacheEmbedder(s.voyage_embed_model, s.voyage_dimension)
            self.available = True
            logger.info("Semantic cache ready (threshold=%.3f, ttl=%ds)", self.threshold, self.ttl)
        except Exception as exc:  # noqa: BLE001 - degrade, never crash startup
            logger.warning("Semantic cache unavailable — running no-op (degraded): %s", str(exc)[:160])
            self.redis = None
            self.embedder = None
            self.available = False

    @track(name="cache-lookup")
    def get(self, query: str) -> tuple[Optional[dict[str, Any]], Optional["np.ndarray"]]:
        """Return ``(hit_or_None, query_embedding)``.

        The embedding is returned even on a miss so the caller can reuse it for
        retrieval and ``set`` — it is the *same* voyage-4-lite query vector
        (verified identical, cosine 1.0), so re-embedding the same query 2-3× per
        miss is pure waste.
        """
        if not self.available or not query or not query.strip():
            return None, None
        start = time.time()
        try:
            vec = self.embedder.embed(query)
            knn = (
                Query("*=>[KNN 1 @embedding $vec AS distance]")
                .return_fields("query", "answer", "query_type", "timestamp", "distance")
                .dialect(2)
            )
            results = self.redis.ft(INDEX_NAME).search(knn, query_params={"vec": vec.tobytes()})
            lookup_ms = (time.time() - start) * 1000

            if getattr(results, "total", 0) > 0:
                top = results.docs[0]
                distance = float(self._decode(top.distance))
                if distance < self.threshold:
                    self._hits += 1
                    contexts_raw = self.redis.hget(self._decode(top.id), "contexts")
                    contexts = json.loads(contexts_raw) if contexts_raw else []
                    update_current_span(output={"cache_hit": True, "distance": round(distance, 4)})
                    return {
                        "answer": self._decode(top.answer),
                        "contexts": contexts,
                        "original_query": self._decode(top.query),
                        "query_type": self._decode(getattr(top, "query_type", "")) or "FACTUAL",
                        "distance": distance,
                        "cache_lookup_ms": round(lookup_ms, 1),
                    }, vec

            self._misses += 1
            update_current_span(output={"cache_hit": False, "lookup_ms": round(lookup_ms, 1)})
            return None, vec
        except Exception as exc:  # noqa: BLE001 - lookup failure is non-fatal
            self._misses += 1
            logger.debug("Cache lookup error: %s", str(exc)[:120])
            return None, None

    def set(
        self,
        query: str,
        answer: str,
        contexts: list[dict[str, Any]],
        query_type: str = "FACTUAL",
        embedding: Optional["np.ndarray"] = None,
    ) -> None:
        if not self.available or not query or not answer:
            return
        try:
            embedding = embedding if embedding is not None else self.embedder.embed(query)
            key = f"{KEY_PREFIX}{hashlib.md5(query.encode()).hexdigest()}"
            self.redis.hset(
                key,
                mapping={
                    "query": query,
                    "answer": answer,
                    "query_type": query_type,
                    "contexts": json.dumps(contexts),
                    "timestamp": str(time.time()),
                    "embedding": embedding.tobytes(),
                },
            )
            if self.ttl:
                self.redis.expire(key, self.ttl)
        except Exception as exc:  # noqa: BLE001 - cache write is non-fatal
            logger.debug("Cache write error: %s", str(exc)[:120])

    def get_stats(self) -> dict[str, Any]:
        total = self._hits + self._misses
        num_docs = 0
        if self.available:
            try:
                info = self.redis.ft(INDEX_NAME).info()
                for key in ("num_docs", b"num_docs"):
                    if key in info:
                        num_docs = int(info[key])
                        break
            except Exception:  # noqa: BLE001
                pass
        return {
            "cache_hits": self._hits,
            "cache_misses": self._misses,
            "total_queries": total,
            "hit_rate_percent": round((self._hits / total * 100) if total else 0.0, 1),
            "num_cached_entries": num_docs,
            "distance_threshold": self.threshold,
            "available": self.available,
        }

    def is_healthy(self) -> bool:
        if not self.available:
            return False
        try:
            self.redis.ping()
            return True
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _decode(value: Any) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value) if value is not None else ""
