"""Shared test fixtures (plan §10.2).

Hermetic by construction: the socket guard fails any unit test that opens a real
connection, and every LLM/vector/Redis dependency is faked here. Tests inject these
fakes through ``app.services.set_services`` — the one place the app reads services.
"""

from __future__ import annotations

import asyncio
import socket
from contextlib import asynccontextmanager
from typing import Any

import pytest
import pytest_asyncio


# --- Network guard --------------------------------------------------------
@pytest.fixture(autouse=True)
def _no_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    # integration (redis-stack), live (real APIs), and visual (localhost servers +
    # the Playwright CDP socket) all make real connections by design.
    for marker in ("integration", "live", "visual"):
        if request.node.get_closest_marker(marker):
            return

    def _blocked(*_a: object, **_k: object):  # noqa: ANN202
        raise RuntimeError(
            "Network access blocked in a unit test. Mock the call, or mark it "
            "@pytest.mark.integration / @pytest.mark.live."
        )

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)


# --- Opik guard -----------------------------------------------------------
@pytest.fixture(autouse=True)
def _no_opik(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep Opik OFF in unit tests, even when a real OPIK_API_KEY is in .env.

    Without this, the lifespan-based tests call ``configure_opik(real_key)`` which
    can flip the module-global ``OPIK_AVAILABLE`` True for the rest of the process
    (Opik reads its local config), making later Opik calls attempt real network and
    the suite order-dependent. Tests that need Opik 'on' (the prompt-cache test)
    set ``OPIK_AVAILABLE`` themselves *after* this fixture runs.
    """
    from app import observability
    from app.prompts import registry

    monkeypatch.setattr(observability, "OPIK_AVAILABLE", False)
    monkeypatch.setattr(observability, "configure_opik", lambda *a, **k: False)
    registry.reset_prompt_cache()


# --- Dogfood guard --------------------------------------------------------
@pytest.fixture(autouse=True)
def _no_dogfood(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never let a unit test append to the real repo-root dogfood/sessions.jsonl.

    Stub the writer itself (not just the _ENABLED flag) — the app lifespan calls
    ``dogfood.set_enabled(settings.dogfood_enabled)`` on startup, which would
    otherwise flip logging back on mid-test.
    """
    from app import dogfood

    monkeypatch.setattr(dogfood, "_append", lambda *_a, **_k: None)


# --- LLM fakes ------------------------------------------------------------
class _Reply:
    def __init__(self, text: str):
        self.text = text


class _Chunk:
    def __init__(self, content: str):
        self.content = content


class FakeChatGenerator:
    """Stands in for GoogleGenAIChatGenerator. ``run`` returns ``text``; ``run_async``
    replays it word-by-word through the streaming callback. Records calls so tests can
    assert it was (not) invoked."""

    def __init__(self, text: str = "Use Depends() for dependency injection [1]."):
        self.text = text
        self.calls: list[Any] = []

    def run(self, messages: Any = None, **_kw: Any) -> dict:
        self.calls.append(messages)
        return {"replies": [_Reply(self.text)]}

    async def run_async(self, messages: Any = None, streaming_callback: Any = None, **_kw: Any) -> dict:
        self.calls.append(messages)
        if streaming_callback:
            for word in self.text.split(" "):
                await streaming_callback(_Chunk(word + " "))
        return {"replies": [_Reply(self.text)]}


# --- Service fakes --------------------------------------------------------
class FakePipeline:
    def __init__(self, answer: str = "To add JWT auth, use OAuth2PasswordBearer [1].", ready: bool = True):
        from haystack import Document

        self.answer = answer
        self.ready = ready
        self.contexts = [
            Document(
                content="from fastapi.security import OAuth2PasswordBearer ...",
                meta={"file_path": "docs/tutorial/security/oauth2-jwt.md", "category": "docs", "file_type": "markdown"},
                score=0.91,
            )
        ]

    async def retrieve(self, query: str, *, dense_embedding=None, max_retries: int = 3):  # noqa: ANN201
        from app.services.rag_pipeline import RetrievalResult

        if not self.ready:
            raise RuntimeError("pipeline not ready")
        return RetrievalResult(
            contexts=self.contexts,
            metadata={"retrieval_time_seconds": 0.1, "num_contexts": len(self.contexts)},
        )

    async def generate(self, query: str, contexts: Any, prompt_messages: Any) -> str:
        return self.answer

    async def generate_stream(self, query: str, contexts: Any, prompt_messages: Any) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        queue.full_answer = self.answer
        queue.stream_error = None
        queue.fallback_used = False
        queue.fallback_metadata = None
        for word in self.answer.split(" "):
            await queue.put(word + " ")
        await queue.put(None)
        return queue

    def is_healthy(self) -> bool:
        return self.ready


class FakeCache:
    def __init__(self, available: bool = True):
        self.available = available
        self.store: dict[str, dict] = {}
        self._hits = 0
        self._misses = 0

    def get(self, query: str):  # noqa: ANN201 - returns (hit_or_None, embedding)
        if self.available and query in self.store:
            self._hits += 1
            return self.store[query], None
        self._misses += 1
        return None, None

    def set(self, query: str, answer: str, contexts: list, query_type: str = "FACTUAL", embedding=None) -> None:
        if self.available:
            self.store[query] = {
                "answer": answer,
                "contexts": contexts,
                "original_query": query,
                "query_type": query_type,
                "distance": 0.01,
                "cache_lookup_ms": 1.0,
            }

    def is_healthy(self) -> bool:
        return self.available

    def get_stats(self) -> dict:
        return {"cache_hits": self._hits, "cache_misses": self._misses, "available": self.available}


class FakeRouter:
    def __init__(self, category: str = "HOW_TO"):
        self.category = category

    async def classify(self, query: str) -> dict:
        return {"category": self.category, "confidence": 0.9}

    def build_prompt(self, query: str, contexts: Any, query_type: str) -> list:
        from haystack.dataclasses import ChatMessage

        return [ChatMessage.from_system("system"), ChatMessage.from_user(query)]

    def is_healthy(self) -> bool:
        return True


# --- Injected API client --------------------------------------------------
_DEFAULT_REWRITE = "How do I set the JWT token to expire in 30 minutes?"


@asynccontextmanager
async def build_client(*, rag=None, cache=None, conversation=None, router=None, rewriter_text: str = _DEFAULT_REWRITE):
    """The single app-wiring path: inject fakes (conversation is a real
    ConversationService on fakeredis so memory + rewrite are genuinely exercised),
    build the app, manage its lifespan, and yield an httpx client. ``api_client``
    is just ``build_client()`` with the fakes exposed for assertions."""
    import fakeredis
    from asgi_lifespan import LifespanManager
    from httpx import ASGITransport, AsyncClient

    from app.services import reset_services, set_services
    from app.services.conversation import ConversationService

    reset_services()
    cache = cache or FakeCache()
    conversation = conversation or ConversationService(
        redis_client=fakeredis.FakeRedis(decode_responses=True),
        rewriter=FakeChatGenerator(text=rewriter_text),
    )
    set_services(rag=rag or FakePipeline(), cache=cache, conversation=conversation, router=router or FakeRouter())

    from app.main import create_app

    app = create_app()
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            client.fake_cache = cache  # exposed for assertions
            client.fake_conversation = conversation
            yield client
    reset_services()


@pytest_asyncio.fixture
async def api_client():
    """All services faked; the common case for endpoint tests."""
    async with build_client() as client:
        yield client
