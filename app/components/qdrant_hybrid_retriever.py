"""Hybrid retriever using Qdrant's native API with explicit prefetch limits.

Adapted from the week-3 retriever (proven across all retrieval experiments). The
explicit prefetch limits are the fix for Haystack's built-in QdrantHybridRetriever,
which under-fetches (~10-20 docs/vector) instead of the requested top_k.

Flow: dense prefetch (100) + sparse prefetch (100) → RRF fusion → top_k (50) → reranker.
The collection stores vectors named ``text-dense`` / ``text-sparse``.
"""

from __future__ import annotations

import logging
from typing import Any

from haystack import Document, component, default_from_dict, default_to_dict
from qdrant_client import QdrantClient, models

logger = logging.getLogger(__name__)


@component
class QdrantHybridRetriever:
    def __init__(
        self,
        url: str,
        api_key: str,
        collection_name: str,
        top_k: int = 50,
        dense_prefetch_limit: int = 100,
        sparse_prefetch_limit: int = 100,
    ):
        self.url = url
        self.api_key = api_key
        self.collection_name = collection_name
        self.top_k = top_k  # output AFTER RRF fusion
        self.dense_prefetch_limit = dense_prefetch_limit
        self.sparse_prefetch_limit = sparse_prefetch_limit
        self.client: QdrantClient | None = None

    def warm_up(self) -> None:
        if self.client is None:
            self.client = QdrantClient(url=self.url, api_key=self.api_key, prefer_grpc=True, timeout=60)
            logger.debug(
                "Hybrid retriever ready (dense=%d, sparse=%d -> RRF top_k=%d)",
                self.dense_prefetch_limit,
                self.sparse_prefetch_limit,
                self.top_k,
            )

    def to_dict(self) -> dict[str, Any]:
        return default_to_dict(
            self,
            url=self.url,
            api_key=self.api_key,
            collection_name=self.collection_name,
            top_k=self.top_k,
            dense_prefetch_limit=self.dense_prefetch_limit,
            sparse_prefetch_limit=self.sparse_prefetch_limit,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QdrantHybridRetriever":
        return default_from_dict(cls, data)

    @component.output_types(documents=list[Document])
    def run(self, query_embedding: list[float], query_sparse_embedding: Any) -> dict[str, Any]:
        if self.client is None:
            self.warm_up()

        sparse_vector = models.SparseVector(
            indices=query_sparse_embedding.indices,
            values=query_sparse_embedding.values,
        )

        response = self.client.query_points(
            collection_name=self.collection_name,
            prefetch=[
                models.Prefetch(query=query_embedding, using="text-dense", limit=self.dense_prefetch_limit),
                models.Prefetch(query=sparse_vector, using="text-sparse", limit=self.sparse_prefetch_limit),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=self.top_k,
            with_payload=True,
        )
        logger.debug("Hybrid retrieval returned %d docs after RRF", len(response.points))

        documents: list[Document] = []
        for point in response.points:
            payload = point.payload or {}
            if isinstance(payload.get("meta"), dict):
                metadata = payload["meta"]
            else:
                metadata = {k: v for k, v in payload.items() if k not in ("content", "blob", "id", "score")}
            documents.append(
                Document(
                    id=str(point.id),
                    content=payload.get("content", ""),
                    meta=metadata,
                    score=point.score,
                )
            )
        return {"documents": documents}
