"""Production RAG pipeline — T1b (hybrid + Voyage rerank), split retrieve/generate.

Retrieval (Haystack pipeline): VoyageTextEmbedder + FastembedSparseTextEmbedder →
QdrantHybridRetriever (prefetch 100/100 → RRF top-50) → VoyageReranker (→ top-10).
Generation: direct Gemini call with the router-selected prompt; primary
``gemini-2.5-flash`` with a ``flash-lite`` fallback (retry once on 503, fall back
immediately on 429). ``generate_stream`` streams tokens through an ``asyncio.Queue``.

Resilient init: if creds are missing or the pipeline can't be built, the service
marks itself not-ready (``is_healthy`` False) instead of raising — the app still
starts and ``/health`` reports degraded (AC1.5). Heavy Haystack integrations are
imported lazily inside ``_build`` so unit tests that never build a real pipeline
stay light.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from haystack import Document
from haystack.dataclasses import ChatMessage

from app.config import get_settings
from app.observability import track, update_current_span

logger = logging.getLogger(__name__)

# Let Haystack emit content traces when Opik is wired up.
os.environ.setdefault("HAYSTACK_CONTENT_TRACING_ENABLED", "true")


@dataclass
class RetrievalResult:
    contexts: list[Document]
    metadata: dict[str, Any] = field(default_factory=dict)


def _is_rate_limit(err: Exception) -> bool:
    e = str(err).lower()
    return any(s in e for s in ("429", "rate limit", "resource exhausted", "quota"))


def _is_server_error(err: Exception) -> bool:
    e = str(err).lower()
    return any(s in e for s in ("503", "service unavailable", "overloaded"))


class ProductionRAGPipeline:
    def __init__(self, *, pipeline: Any = None, generator: Any = None, fallback_generator: Any = None):
        s = get_settings()
        self.collection = s.qdrant_collection
        self.dense_model = s.voyage_embed_model
        self.gemini_model = s.llm_model
        self.fallback_model = s.llm_fallback_model
        self._settings = s

        self.pipeline = pipeline
        self.generator = generator
        self.fallback_generator = fallback_generator
        self.dense_embedder = None  # standalone (real build); None in injected/test mode
        self.ready = pipeline is not None and generator is not None

        if not self.ready and pipeline is None and generator is None:
            self._build()

    def _build(self) -> None:
        s = self._settings
        if not (s.qdrant_url and s.qdrant_api_key and s.voyage_api_key and s.google_api_key):
            missing = [
                k
                for k, v in {
                    "QDRANT_URL": s.qdrant_url,
                    "QDRANT_API_KEY": s.qdrant_api_key,
                    "VOYAGE_API_KEY": s.voyage_api_key,
                    "GOOGLE_API_KEY": s.google_api_key,
                }.items()
                if not v
            ]
            logger.warning("RAG pipeline not built — missing creds: %s (running degraded)", missing)
            self.ready = False
            return
        try:
            from haystack import Pipeline
            from haystack_integrations.components.embedders.fastembed import (
                FastembedSparseTextEmbedder,
            )
            from haystack_integrations.components.embedders.voyage_embedders import (
                VoyageTextEmbedder,
            )
            from haystack_integrations.components.generators.google_genai import (
                GoogleGenAIChatGenerator,
            )

            from app.components import QdrantHybridRetriever, VoyageReranker

            # The dense embedder is kept OUT of the pipeline graph so its query
            # vector can be supplied from the semantic-cache lookup (the same
            # voyage-4-lite vector) instead of re-embedding the query. The graph
            # is sparse → retriever → reranker with retriever.query_embedding as a
            # supplied input.
            self.dense_embedder = VoyageTextEmbedder(
                model=s.voyage_embed_model, output_dimension=s.voyage_dimension
            )
            if hasattr(self.dense_embedder, "warm_up"):
                self.dense_embedder.warm_up()

            pipe = Pipeline()
            pipe.add_component("sparse_embedder", FastembedSparseTextEmbedder(model=s.sparse_model))
            pipe.add_component(
                "retriever",
                QdrantHybridRetriever(
                    url=s.qdrant_url,
                    api_key=s.qdrant_api_key,
                    collection_name=s.qdrant_collection,
                    top_k=s.rerank_input,
                    dense_prefetch_limit=s.dense_prefetch,
                    sparse_prefetch_limit=s.sparse_prefetch,
                ),
            )
            pipe.add_component(
                "reranker",
                VoyageReranker(model=s.voyage_rerank_model, top_k=s.rerank_top_k, api_key=s.voyage_api_key),
            )
            pipe.connect("sparse_embedder.sparse_embedding", "retriever.query_sparse_embedding")
            pipe.connect("retriever.documents", "reranker.documents")
            for name in ("sparse_embedder", "retriever", "reranker"):
                comp = pipe.get_component(name)
                if hasattr(comp, "warm_up"):
                    comp.warm_up()

            self.pipeline = pipe
            self.generator = GoogleGenAIChatGenerator(model=s.llm_model)
            self.fallback_generator = GoogleGenAIChatGenerator(model=s.llm_fallback_model)
            self.ready = True
            logger.info(
                "RAG pipeline ready: %s | dense %s + BM25 -> RRF(%d) -> rerank(%d)",
                s.qdrant_collection,
                s.voyage_embed_model,
                s.rerank_input,
                s.rerank_top_k,
            )
        except Exception as exc:  # noqa: BLE001 - degrade, never crash startup
            logger.warning("RAG pipeline build failed (running degraded): %s", str(exc)[:200])
            self.ready = False

    @track(name="retrieve")
    async def retrieve(self, query: str, *, dense_embedding: Any = None, max_retries: int = 3) -> RetrievalResult:
        if not self.ready:
            raise RuntimeError("RAG pipeline not ready (missing credentials or failed init).")
        start = time.time()
        # Reuse the cache-lookup's query vector when given; otherwise embed here.
        if dense_embedding is None and self.dense_embedder is not None:
            dense_embedding = self.dense_embedder.run(text=query)["embedding"]
        elif dense_embedding is not None and not isinstance(dense_embedding, list):
            dense_embedding = dense_embedding.tolist()  # np.ndarray -> list[float]
        for attempt in range(max_retries):
            try:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: self.pipeline.run(
                        data={
                            "sparse_embedder": {"text": query},
                            "retriever": {"query_embedding": dense_embedding or []},
                            "reranker": {"query": query},
                        }
                    ),
                )
                contexts = result["reranker"]["documents"]
                elapsed = round(time.time() - start, 3)
                update_current_span(output={"num_contexts": len(contexts), "retrieval_time_seconds": elapsed})
                return RetrievalResult(
                    contexts=contexts,
                    metadata={"retrieval_time_seconds": elapsed, "num_contexts": len(contexts), "attempt": attempt + 1},
                )
            except Exception as exc:  # noqa: BLE001
                if attempt < max_retries - 1:
                    wait = (2**attempt) + 1
                    logger.warning("Retrieval attempt %d failed: %s — retry in %ds", attempt + 1, str(exc)[:80], wait)
                    await asyncio.sleep(wait)
                else:
                    raise RuntimeError(f"Retrieval failed after {max_retries} attempts: {exc}") from exc

    @track(name="generate")
    async def generate(self, query: str, contexts: list[Document], prompt_messages: list[ChatMessage]) -> str:
        if not self.ready:
            raise RuntimeError("RAG pipeline not ready.")
        loop = asyncio.get_running_loop()
        original_error: Optional[Exception] = None
        for attempt in range(2):
            try:
                result = await loop.run_in_executor(None, lambda: self.generator.run(messages=prompt_messages))
                return result["replies"][0].text
            except Exception as exc:  # noqa: BLE001
                original_error = exc
                if _is_rate_limit(exc):
                    break
                if _is_server_error(exc) and attempt == 0:
                    await asyncio.sleep(2)
                    continue
                if _is_server_error(exc) and attempt == 1:
                    break
                raise
        try:
            result = await loop.run_in_executor(None, lambda: self.fallback_generator.run(messages=prompt_messages))
            update_current_span(metadata={"fallback_used": True, "original_error": str(original_error)})
            return result["replies"][0].text
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Generation failed on primary and fallback: {exc}") from exc

    async def generate_stream(
        self, query: str, contexts: list[Document], prompt_messages: list[ChatMessage]
    ) -> asyncio.Queue:
        """Stream tokens via an asyncio.Queue (None sentinel on completion).

        ``queue.full_answer`` holds the final text; ``queue.stream_error`` an
        exception if generation failed; ``queue.fallback_used`` / ``fallback_metadata``
        record a fallback to the lite model.
        """
        queue: asyncio.Queue = asyncio.Queue()
        queue.full_answer = ""
        queue.stream_error = None
        queue.fallback_used = False
        queue.fallback_metadata = None

        if not self.ready:
            queue.stream_error = RuntimeError("RAG pipeline not ready.")
            queue.put_nowait(None)
            return queue

        emitted = {"any": False}  # once tokens reach the client, retry/fallback would duplicate them

        async def _callback(chunk) -> None:
            if chunk.content:
                emitted["any"] = True
                await queue.put(chunk.content)

        async def _run() -> None:
            original_error: Optional[Exception] = None
            try:
                for attempt in range(2):
                    try:
                        result = await self.generator.run_async(messages=prompt_messages, streaming_callback=_callback)
                        queue.full_answer = result["replies"][0].text
                        return
                    except Exception as exc:  # noqa: BLE001
                        original_error = exc
                        # A failure after tokens were already streamed can't be retried
                        # without garbling the client's output — surface it as an error.
                        if emitted["any"]:
                            raise
                        if _is_rate_limit(exc):
                            break
                        if _is_server_error(exc) and attempt == 0:
                            await asyncio.sleep(2)
                            continue
                        if _is_server_error(exc) and attempt == 1:
                            break
                        raise
                result = await self.fallback_generator.run_async(messages=prompt_messages, streaming_callback=_callback)
                queue.full_answer = result["replies"][0].text
                queue.fallback_used = True
                queue.fallback_metadata = {"fallback_model": self.fallback_model, "original_error": str(original_error)}
            except Exception as exc:  # noqa: BLE001
                queue.full_answer = ""
                queue.stream_error = exc
            finally:
                # Exactly one sentinel, on every exit path — including CancelledError
                # if the consumer disconnects — so the reader never hangs.
                queue.put_nowait(None)

        # Keep a strong reference: the loop only weakly tracks tasks, so a bare
        # create_task can be GC'd and cancelled mid-generation.
        queue.task = asyncio.create_task(_run())
        return queue

    def is_healthy(self) -> bool:
        return self.ready
