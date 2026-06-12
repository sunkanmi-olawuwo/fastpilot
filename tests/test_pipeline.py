"""ProductionRAGPipeline generate/stream/retrieve logic with scripted fakes.

Exercises the 503→retry / 429→fallback ladder and the streaming queue without any
network — the real pipeline *build* (Voyage/FastEmbed/Qdrant) is a live test.
"""

from __future__ import annotations

import pytest
from app.services.rag_pipeline import ProductionRAGPipeline


class _Reply:
    def __init__(self, text):
        self.text = text


class _Chunk:
    def __init__(self, content):
        self.content = content


class ScriptedGenerator:
    """Each call consumes the next behavior: a str → reply, an Exception → raised.
    The last behavior repeats if called again."""

    def __init__(self, behaviors):
        self.behaviors = list(behaviors)
        self.i = 0

    def _next(self):
        b = self.behaviors[min(self.i, len(self.behaviors) - 1)]
        self.i += 1
        if isinstance(b, Exception):
            raise b
        return b

    def run(self, messages=None, **_kw):
        return {"replies": [_Reply(self._next())]}

    async def run_async(self, messages=None, streaming_callback=None, **_kw):
        b = self.behaviors[min(self.i, len(self.behaviors) - 1)]
        self.i += 1
        if isinstance(b, Exception):
            raise b
        if streaming_callback:
            for word in b.split(" "):
                await streaming_callback(_Chunk(word + " "))
        return {"replies": [_Reply(b)]}


class _FakeHaystackPipeline:
    def run(self, data=None):
        from haystack import Document

        return {"reranker": {"documents": [Document(content="ctx", meta={"file_path": "a.md"}, score=0.9)]}}


def _pipeline(primary, fallback=None):
    return ProductionRAGPipeline(
        pipeline=_FakeHaystackPipeline(),
        generator=primary,
        fallback_generator=fallback or ScriptedGenerator(["fallback answer"]),
    )


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    async def _instant(_seconds):
        return None

    monkeypatch.setattr("app.services.rag_pipeline.asyncio.sleep", _instant)


async def test_retrieve_returns_contexts():
    p = _pipeline(ScriptedGenerator(["x"]))
    result = await p.retrieve("How do I add auth?")
    assert len(result.contexts) == 1
    assert result.metadata["num_contexts"] == 1


async def test_generate_happy_path():
    p = _pipeline(ScriptedGenerator(["the answer"]))
    assert await p.generate("q", [], []) == "the answer"


async def test_generate_retries_once_on_503_then_succeeds():
    primary = ScriptedGenerator([RuntimeError("503 service unavailable"), "recovered"])
    p = _pipeline(primary)
    assert await p.generate("q", [], []) == "recovered"
    assert primary.i == 2  # failed once, retried, succeeded


async def test_generate_falls_back_immediately_on_429():
    primary = ScriptedGenerator([RuntimeError("429 rate limit exceeded")])
    p = _pipeline(primary, fallback=ScriptedGenerator(["lite answer"]))
    assert await p.generate("q", [], []) == "lite answer"
    assert primary.i == 1  # no retry on rate limit


async def test_generate_raises_on_unknown_error():
    p = _pipeline(ScriptedGenerator([ValueError("boom")]))
    with pytest.raises(ValueError):
        await p.generate("q", [], [])


async def test_generate_stream_yields_tokens():
    p = _pipeline(ScriptedGenerator(["hello world there"]))
    queue = await p.generate_stream("q", [], [])
    tokens = []
    while True:
        tok = await queue.get()
        if tok is None:
            break
        tokens.append(tok)
    assert "".join(tokens).strip() == "hello world there"
    assert queue.full_answer == "hello world there"
    assert queue.stream_error is None


async def test_generate_stream_captures_error():
    p = _pipeline(ScriptedGenerator([ValueError("stream boom")]))
    queue = await p.generate_stream("q", [], [])
    assert await queue.get() is None  # only the sentinel
    assert queue.stream_error is not None


async def test_not_ready_pipeline_degrades():
    p = ProductionRAGPipeline.__new__(ProductionRAGPipeline)
    p.ready = False
    with pytest.raises(RuntimeError):
        await p.retrieve("q")
    with pytest.raises(RuntimeError):
        await p.generate("q", [], [])  # generate also guards on readiness
    queue = await p.generate_stream("q", [], [])
    assert await queue.get() is None
    assert queue.stream_error is not None


def test_is_healthy_reflects_ready_flag():
    p = ProductionRAGPipeline.__new__(ProductionRAGPipeline)
    p.ready = True
    assert p.is_healthy() is True
    p.ready = False
    assert p.is_healthy() is False


# --- _build degraded path (no creds → not-ready, never raises) -------------
def test_build_degrades_without_credentials():
    from types import SimpleNamespace

    p = ProductionRAGPipeline.__new__(ProductionRAGPipeline)
    p._settings = SimpleNamespace(qdrant_url="", qdrant_api_key="", voyage_api_key="", google_api_key="")
    p.ready = True
    p._build()  # missing creds → logs which are absent, marks not-ready, no exception
    assert p.ready is False


# --- retrieve embedding + retry ladder -------------------------------------
class _StubDenseEmbedder:
    def __init__(self):
        self.calls = 0

    def run(self, text):
        self.calls += 1
        return {"embedding": [0.1, 0.2, 0.3]}


async def test_retrieve_embeds_when_no_vector_supplied():
    p = _pipeline(ScriptedGenerator(["x"]))
    p.dense_embedder = _StubDenseEmbedder()
    await p.retrieve("how do I add auth?")  # dense_embedding=None → embed here
    assert p.dense_embedder.calls == 1


async def test_retrieve_converts_ndarray_vector_to_list():
    import numpy as np

    captured = {}

    class _CapturingPipeline:
        def run(self, data=None):
            from haystack import Document

            captured["vec"] = data["retriever"]["query_embedding"]
            return {"reranker": {"documents": [Document(content="c", meta={"file_path": "a.md"}, score=0.9)]}}

    p = ProductionRAGPipeline(
        pipeline=_CapturingPipeline(),
        generator=ScriptedGenerator(["x"]),
        fallback_generator=ScriptedGenerator(["y"]),
    )
    await p.retrieve("q", dense_embedding=np.array([0.4, 0.5], dtype=np.float32))
    assert captured["vec"] == [pytest.approx(0.4), pytest.approx(0.5)]  # ndarray → list


async def test_retrieve_retries_then_raises_after_max():
    class _AlwaysFails:
        def run(self, data=None):
            raise RuntimeError("qdrant timeout")

    p = ProductionRAGPipeline(
        pipeline=_AlwaysFails(), generator=ScriptedGenerator(["x"]), fallback_generator=ScriptedGenerator(["y"])
    )
    with pytest.raises(RuntimeError, match="Retrieval failed after"):
        await p.retrieve("q", dense_embedding=[0.1], max_retries=2)


async def test_retrieve_retries_then_succeeds():
    class _FailsOnce:
        def __init__(self):
            self.n = 0

        def run(self, data=None):
            from haystack import Document

            self.n += 1
            if self.n == 1:
                raise RuntimeError("503 transient")
            return {"reranker": {"documents": [Document(content="c", meta={"file_path": "a.md"}, score=0.9)]}}

    p = ProductionRAGPipeline(
        pipeline=_FailsOnce(), generator=ScriptedGenerator(["x"]), fallback_generator=ScriptedGenerator(["y"])
    )
    result = await p.retrieve("q", dense_embedding=[0.1], max_retries=3)
    assert len(result.contexts) == 1
    assert result.metadata["attempt"] == 2  # succeeded on the retry


# --- generate fallback ladder ----------------------------------------------
async def test_generate_503_twice_then_fallback():
    primary = ScriptedGenerator([RuntimeError("503 unavailable"), RuntimeError("503 still unavailable")])
    p = _pipeline(primary, fallback=ScriptedGenerator(["lite answer"]))
    assert await p.generate("q", [], []) == "lite answer"  # both 503 → fall back to lite


async def test_generate_raises_when_fallback_also_fails():
    primary = ScriptedGenerator([RuntimeError("429 rate limit")])
    p = _pipeline(primary, fallback=ScriptedGenerator([ValueError("lite also down")]))
    with pytest.raises(RuntimeError, match="primary and fallback"):
        await p.generate("q", [], [])


# --- generate_stream fallback + post-emit failure --------------------------
async def test_generate_stream_falls_back_on_rate_limit():
    primary = ScriptedGenerator([RuntimeError("429 rate limit")])  # raises before any token
    p = _pipeline(primary, fallback=ScriptedGenerator(["lite streamed answer"]))
    queue = await p.generate_stream("q", [], [])
    tokens = []
    while (tok := await queue.get()) is not None:
        tokens.append(tok)
    assert "".join(tokens).strip() == "lite streamed answer"
    assert queue.fallback_used is True
    assert queue.fallback_metadata["fallback_model"] == p.fallback_model


async def test_generate_stream_retries_503_then_falls_back():
    # 503 on both attempts (no tokens emitted) → exhaust retries → fall back to lite.
    primary = ScriptedGenerator([RuntimeError("503 unavailable"), RuntimeError("503 unavailable")])
    p = _pipeline(primary, fallback=ScriptedGenerator(["lite recovered answer"]))
    queue = await p.generate_stream("q", [], [])
    tokens = []
    while (tok := await queue.get()) is not None:
        tokens.append(tok)
    assert "".join(tokens).strip() == "lite recovered answer"
    assert queue.fallback_used is True


async def test_generate_stream_failure_after_emit_is_surfaced():
    class _EmitThenDie:
        async def run_async(self, messages=None, streaming_callback=None, **_kw):
            if streaming_callback:
                await streaming_callback(_Chunk("partial "))  # tokens already on the wire
            raise RuntimeError("died mid-stream")

    p = _pipeline(_EmitThenDie())
    queue = await p.generate_stream("q", [], [])
    seen = []
    while (tok := await queue.get()) is not None:
        seen.append(tok)
    assert seen == ["partial "]  # the emitted token reached the client
    assert queue.stream_error is not None  # ...and the failure is reported, not retried
    assert queue.full_answer == ""
