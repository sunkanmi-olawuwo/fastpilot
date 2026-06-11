"""Reranker using Voyage AI's rerank-2.5 (Haystack-compatible).

Adapted from week-3. Includes graceful fallback: on API failure it returns the
input documents truncated to top_k rather than crashing the pipeline.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import voyageai
from haystack import Document, component

logger = logging.getLogger(__name__)


@component
class VoyageReranker:
    def __init__(self, model: str = "rerank-2.5", top_k: int = 10, api_key: Optional[str] = None):
        self.model = model
        self.top_k = top_k
        self.api_key = api_key or os.getenv("VOYAGE_API_KEY")
        self.client: voyageai.Client | None = None
        if not self.api_key:
            raise ValueError("Voyage API key required (set VOYAGE_API_KEY or pass api_key).")

    def warm_up(self) -> None:
        if self.client is None:
            self.client = voyageai.Client(api_key=self.api_key)
            logger.debug("Voyage reranker ready (model=%s)", self.model)

    @component.output_types(documents=list[Document])
    def run(self, query: str, documents: list[Document], top_k: Optional[int] = None) -> dict[str, Any]:
        if self.client is None:
            self.warm_up()
        if not documents:
            return {"documents": []}

        k = min(top_k if top_k is not None else self.top_k, len(documents))
        doc_texts = [doc.content for doc in documents]

        try:
            reranking = self.client.rerank(query=query, documents=doc_texts, model=self.model, top_k=k)
        except Exception as exc:  # noqa: BLE001 - graceful degradation
            logger.warning("Voyage rerank failed (%s); returning truncated input", str(exc)[:120])
            return {"documents": documents[:k]}

        reranked: list[Document] = []
        for result in reranking.results:
            original = documents[result.index]
            reranked.append(
                Document(
                    id=original.id,
                    content=original.content,
                    meta=dict(original.meta) if original.meta else {},
                    score=result.relevance_score,
                )
            )
        return {"documents": reranked}
