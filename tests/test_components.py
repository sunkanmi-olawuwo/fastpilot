"""Retrieval component units — QdrantHybridRetriever + VoyageReranker.

Both wrap a network client (Qdrant gRPC / Voyage HTTP). We never touch the network:
a stub client returns canned points/results, so the fusion-prefetch wiring, the
payload→Document mapping, and the reranker's graceful fallback are all exercised
hermetically. The real `build` against live services is a `live` test.
"""

from __future__ import annotations

import pytest
from haystack import Document

from app.components.qdrant_hybrid_retriever import QdrantHybridRetriever
from app.components.voyage_reranker import VoyageReranker


# --- Qdrant hybrid retriever ----------------------------------------------
class _Sparse:
    indices = [1, 5, 9]
    values = [0.2, 0.5, 0.3]


class _Point:
    def __init__(self, id, payload, score):
        self.id = id
        self.payload = payload
        self.score = score


class _Resp:
    def __init__(self, points):
        self.points = points


class _StubQdrant:
    def __init__(self, points):
        self._points = points
        self.calls: list[dict] = []

    def query_points(self, **kwargs):
        self.calls.append(kwargs)
        return _Resp(self._points)


def _retriever(points, **kw):
    r = QdrantHybridRetriever(url="http://stub", api_key="k", collection_name="c", **kw)
    r.client = _StubQdrant(points)  # inject → warm_up skipped, no network
    return r


def test_run_maps_payload_with_meta_dict():
    pts = [_Point("p1", {"content": "hello", "meta": {"file_path": "a.md", "category": "docs"}}, 0.87)]
    r = _retriever(pts)
    docs = r.run(query_embedding=[0.1, 0.2], query_sparse_embedding=_Sparse())["documents"]
    assert len(docs) == 1
    assert docs[0].id == "p1"
    assert docs[0].content == "hello"
    assert docs[0].meta == {"file_path": "a.md", "category": "docs"}
    assert docs[0].score == 0.87


def test_run_maps_flat_payload_excluding_reserved_keys():
    # No nested "meta" → metadata is the payload minus content/blob/id/score.
    pts = [_Point(42, {"content": "body", "file_path": "b.md", "score": 0.9, "blob": "x"}, 0.5)]
    docs = _retriever(pts).run(query_embedding=[0.0], query_sparse_embedding=_Sparse())["documents"]
    assert docs[0].id == "42"  # coerced to str
    assert docs[0].meta == {"file_path": "b.md"}  # content/score/blob stripped


def test_run_passes_prefetch_limits_and_topk():
    r = _retriever([], top_k=7, dense_prefetch_limit=33, sparse_prefetch_limit=44)
    r.run(query_embedding=[0.1], query_sparse_embedding=_Sparse())
    call = r.client.calls[0]
    assert call["collection_name"] == "c"
    assert call["limit"] == 7
    prefetch = {p.using: p.limit for p in call["prefetch"]}
    assert prefetch == {"text-dense": 33, "text-sparse": 44}


def test_run_empty_result_returns_no_documents():
    assert _retriever([]).run(query_embedding=[0.1], query_sparse_embedding=_Sparse())["documents"] == []


def test_warm_up_builds_client_once(monkeypatch):
    built = {"n": 0}

    def _fake_client(**kw):
        built["n"] += 1
        return _StubQdrant([])

    monkeypatch.setattr("app.components.qdrant_hybrid_retriever.QdrantClient", _fake_client)
    r = QdrantHybridRetriever(url="http://stub", api_key="k", collection_name="c")
    assert r.client is None
    r.warm_up()
    r.warm_up()  # idempotent — second call must not rebuild
    assert built["n"] == 1
    # run() with client None also triggers warm_up (covers the None-guard branch).
    r2 = QdrantHybridRetriever(url="http://stub", api_key="k", collection_name="c")
    r2.run(query_embedding=[0.1], query_sparse_embedding=_Sparse())
    assert r2.client is not None


def test_to_dict_from_dict_roundtrip():
    r = QdrantHybridRetriever(url="http://stub", api_key="k", collection_name="c", top_k=5)
    data = r.to_dict()
    clone = QdrantHybridRetriever.from_dict(data)
    assert clone.collection_name == "c"
    assert clone.top_k == 5
    assert clone.url == "http://stub"


# --- Voyage reranker ------------------------------------------------------
class _RerankItem:
    def __init__(self, index, score):
        self.index = index
        self.relevance_score = score


class _Reranking:
    def __init__(self, items):
        self.results = items


class _StubVoyage:
    def __init__(self, items=None, raises=False):
        self._items = items or []
        self._raises = raises
        self.calls: list[dict] = []

    def rerank(self, query, documents, model, top_k):
        self.calls.append({"query": query, "documents": documents, "model": model, "top_k": top_k})
        if self._raises:
            raise RuntimeError("voyage 500")
        return _Reranking(self._items)


def _docs():
    return [
        Document(content="alpha", meta={"file_path": "a.md"}, score=0.1),
        Document(content="bravo", meta={"file_path": "b.md"}, score=0.2),
        Document(content="charlie", meta={"file_path": "c.md"}, score=0.3),
    ]


def _reranker(stub, **kw):
    rr = VoyageReranker(api_key="test", **kw)
    rr.client = stub  # inject → warm_up skipped
    return rr


def test_rerank_reorders_and_applies_scores():
    # Voyage says doc[2] is best, then doc[0]; meta is preserved, score is the relevance.
    stub = _StubVoyage([_RerankItem(2, 0.95), _RerankItem(0, 0.40)])
    out = _reranker(stub, top_k=2).run(query="q", documents=_docs())["documents"]
    assert [d.content for d in out] == ["charlie", "alpha"]
    assert out[0].score == 0.95
    assert out[0].meta == {"file_path": "c.md"}
    assert stub.calls[0]["top_k"] == 2  # k = min(top_k, len(docs))


def test_rerank_topk_override_clamps_to_doc_count():
    stub = _StubVoyage([_RerankItem(0, 0.9)])
    _reranker(stub, top_k=10).run(query="q", documents=_docs(), top_k=99)
    assert stub.calls[0]["top_k"] == 3  # clamped to the 3 docs available


def test_rerank_empty_documents_short_circuits():
    stub = _StubVoyage([])
    out = _reranker(stub).run(query="q", documents=[])["documents"]
    assert out == []
    assert stub.calls == []  # never called the API for an empty list


def test_rerank_api_failure_returns_truncated_input():
    stub = _StubVoyage(raises=True)
    docs = _docs()
    out = _reranker(stub, top_k=2).run(query="q", documents=docs)["documents"]
    assert out == docs[:2]  # graceful fallback: original order, truncated to k


def test_reranker_requires_api_key(monkeypatch):
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    with pytest.raises(ValueError):
        VoyageReranker(api_key=None)


def test_reranker_reads_key_from_env(monkeypatch):
    monkeypatch.setenv("VOYAGE_API_KEY", "from-env")
    assert VoyageReranker().api_key == "from-env"


def test_reranker_warm_up_builds_client(monkeypatch):
    built = {"n": 0}

    def _fake_voyage(api_key=None):
        built["n"] += 1
        return _StubVoyage([])

    monkeypatch.setattr("app.components.voyage_reranker.voyageai.Client", _fake_voyage)
    rr = VoyageReranker(api_key="test")
    assert rr.client is None
    rr.warm_up()
    rr.warm_up()
    assert built["n"] == 1
