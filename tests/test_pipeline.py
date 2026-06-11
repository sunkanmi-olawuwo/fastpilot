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
    queue = await p.generate_stream("q", [], [])
    assert await queue.get() is None
    assert queue.stream_error is not None
