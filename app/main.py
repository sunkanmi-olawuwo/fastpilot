"""FastPilot FastAPI backend.

Request flow (POST /query): InputGuard → rewrite-if-follow-up → semantic cache →
classify ∥ retrieve → build prompt → generate → cache → store turn → dogfood log →
respond. Streaming (/query/stream) is the SSE version.

Built via an app factory so tests get isolated instances; services are reached
through the ``app.services`` getters (injectable in tests). Resilient lifespan:
missing creds or a downed Redis degrade gracefully — the app still starts and
``/health`` reports the truth (AC1.5).

Blocking service I/O (Redis, Voyage embed inside the cache) is offloaded with
``asyncio.to_thread`` so a slow dependency can't stall the whole event loop —
matching the ``run_in_executor`` pattern the pipeline already uses for retrieve/
generate. ``to_thread`` propagates contextvars, so Opik spans still nest.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from app import dogfood, observability
from app.augmentations.agent_orchestrator import AgentOrchestrator, extract_code
from app.augmentations.code_executor import get_executor
from app.augmentations.rate_limit import RateLimiter
from app.augmentations.security import REFUSAL_MESSAGE, get_input_guard
from app.config import get_settings
from app.formatting import source_label
from app.logging_config import configure_logging
from app.models import (
    AgentRequest,
    ContextItem,
    ConversationMessage,
    ConversationResponse,
    ExecuteRequest,
    ExecuteResult,
    FeedbackRequest,
    FeedbackResponse,
    FixRequest,
    FixResponse,
    HealthResponse,
    MetricsResponse,
    QueryRequest,
    QueryResponse,
)
from app.observability import track
from app.services import (
    get_conversation_service,
    get_query_router,
    get_rag_pipeline,
    get_semantic_cache,
)

logger = logging.getLogger("app.main")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _estimate_cost(num_llm_calls: int) -> float:
    """Rough per-request cost: one embed + one rerank + N Gemini calls."""
    return round(0.0001 + 0.0005 + 0.003 * num_llm_calls, 6)


def _new_msg_id() -> str:
    return f"msg_{uuid.uuid4().hex[:12]}"


def _stream_text_chunks(text: str, chunk_size: int = 3):
    """Word-chunk text for simulated streaming of cache hits (preserves whitespace)."""
    parts = re.split(r"(\s+)", text)
    chunk, words = [], 0
    for part in parts:
        chunk.append(part)
        if part.strip():
            words += 1
            if words >= chunk_size:
                yield "".join(chunk)
                chunk, words = [], 0
    if chunk:
        yield "".join(chunk)


def _format_contexts(contexts) -> list[dict[str, Any]]:
    out = []
    for rank, doc in enumerate(contexts, 1):
        out.append(
            {
                "rank": rank,
                "score": round(doc.score, 4) if doc.score else 0.0,
                "content": doc.content,
                "metadata": {
                    "file_path": source_label(doc.meta),
                    "category": doc.meta.get("category", doc.meta.get("source", "unknown")),
                    "file_type": doc.meta.get("file_type", doc.meta.get("content_type", "unknown")),
                },
            }
        )
    return out


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# Offload the synchronous service calls so they don't block the event loop.
async def _cache_get(cache, query: str):  # noqa: ANN202
    return await asyncio.to_thread(cache.get, query)


async def _cache_set(cache, query: str, answer: str, contexts: list, query_type: str, embedding=None) -> None:
    await asyncio.to_thread(cache.set, query, answer, contexts, query_type, embedding)


async def _add_msg(conv, *args: Any, **kwargs: Any) -> str:
    return await asyncio.to_thread(conv.add_message, *args, **kwargs)


async def _build_prompt(router, *args: Any):  # noqa: ANN202
    return await asyncio.to_thread(router.build_prompt, *args)


class _Services:
    """Bundle of the four services, read off app.state."""

    def __init__(self, app: FastAPI):
        self.pipeline = app.state.pipeline
        self.cache = app.state.cache
        self.conversation = app.state.conversation
        self.router = app.state.router


def _track_metrics(app: FastAPI, latency_ms: float, cost: float) -> None:
    app.state.request_count += 1
    app.state.total_latency_ms += latency_ms
    app.state.total_cost_usd += cost


# ---------------------------------------------------------------------------
# Traced pipeline core (parent trace; child spans nest under it)
# ---------------------------------------------------------------------------
async def _prepare(svc: _Services, query_text: str, session_id: str, use_cache: bool) -> dict:
    """Shared front half of both endpoints: rewrite → cache → (on miss) classify ∥
    retrieve → build prompt. Returns a dict with ``cached`` set on a hit, or the
    classification/retrieval/prompt pieces on a miss."""
    rewrite = await svc.conversation.rewrite_if_needed(query_text, session_id)
    standalone = rewrite["standalone_query"]
    prep: dict = {"standalone": standalone, "is_follow_up": rewrite["is_follow_up"], "cached": None}

    cached, query_embedding = (await _cache_get(svc.cache, standalone)) if use_cache else (None, None)
    prep["query_embedding"] = query_embedding  # reused by retrieve + cache.set (same vector)
    if cached:
        prep["cached"] = cached
        return prep

    # Classification and retrieval both depend only on the standalone query — overlap them.
    # retrieve reuses the cache lookup's dense vector instead of re-embedding.
    classification, retrieval = await asyncio.gather(
        svc.router.classify(standalone),
        svc.pipeline.retrieve(standalone, dense_embedding=query_embedding),
    )
    prep["classification"] = classification
    prep["retrieval"] = retrieval
    prep["prompt_messages"] = await _build_prompt(
        svc.router, standalone, retrieval.contexts, classification["category"]
    )
    return prep


async def _finalize_turn(
    svc: _Services,
    app: FastAPI,
    *,
    session_id: str,
    user_query: str,
    answer: str,
    contexts: list,
    query_type: str,
    cache_hit: bool,
    standalone_query: str | None,
    start: float,
    cost: float,
    fallback_used: bool = False,
) -> tuple[str, float]:
    """The shared back half: persist the turn, count it, and dogfood-log it. One
    place so the four call sites (query/stream × hit/miss) can't drift again.
    Returns ``(msg_id, latency_ms)``; each caller builds its own response shape."""
    await _add_msg(svc.conversation, session_id, "user", user_query)
    msg_id = await _add_msg(
        svc.conversation,
        session_id,
        "assistant",
        answer,
        metadata={"query_type": query_type, "cache_hit": cache_hit},
    )
    latency_ms = round((time.time() - start) * 1000, 2)
    _track_metrics(app, latency_ms, cost)
    dogfood.log_interaction(
        session_id=session_id,
        msg_id=msg_id,
        mode="chat",
        query=user_query,
        answer=answer,
        contexts=contexts,
        cache_hit=cache_hit,
        query_type=query_type,
        standalone_query=standalone_query,
        latency_ms=latency_ms,
        fallback_used=fallback_used,
    )
    return msg_id, latency_ms


@track(name="rag-query")
async def _run_query(svc: _Services, app: FastAPI, query_text: str, session_id: str, use_cache: bool, start: float):
    observability.set_thread_id(session_id)
    trace_id = observability.current_trace_id()
    prep = await _prepare(svc, query_text, session_id, use_cache)
    standalone, is_follow_up = prep["standalone"], prep["is_follow_up"]
    std_log = standalone if is_follow_up else None

    cached = prep["cached"]
    if cached:
        query_type = cached.get("query_type", "FACTUAL")
        msg_id, latency = await _finalize_turn(
            svc,
            app,
            session_id=session_id,
            user_query=query_text,
            answer=cached["answer"],
            contexts=cached["contexts"],
            query_type=query_type,
            cache_hit=True,
            standalone_query=std_log,
            start=start,
            cost=0.0,
        )
        meta = {
            "cache_hit": True,
            "latency_ms": latency,
            "cost_usd": 0.0,
            "query_type": query_type,
            "distance": cached.get("distance", 0),
            "is_follow_up": is_follow_up,
            "standalone_query": std_log,
            "trace_id": trace_id,
        }
        response = QueryResponse(
            answer=cached["answer"],
            contexts=[ContextItem(**c) for c in cached["contexts"]],
            metadata=meta,
            session_id=session_id,
            msg_id=msg_id,
        )
        return response, query_type, True

    classification, retrieval = prep["classification"], prep["retrieval"]
    query_type = classification["category"]
    answer = await svc.pipeline.generate(standalone, retrieval.contexts, prep["prompt_messages"])
    contexts = _format_contexts(retrieval.contexts)
    if use_cache and answer:
        await _cache_set(svc.cache, standalone, answer, contexts, query_type, prep.get("query_embedding"))
    cost = _estimate_cost((2 if is_follow_up else 1) + 1)
    msg_id, latency = await _finalize_turn(
        svc,
        app,
        session_id=session_id,
        user_query=query_text,
        answer=answer,
        contexts=contexts,
        query_type=query_type,
        cache_hit=False,
        standalone_query=std_log,
        start=start,
        cost=cost,
    )
    meta = {
        "cache_hit": False,
        "latency_ms": latency,
        "cost_usd": cost,
        "query_type": query_type,
        "query_type_confidence": classification["confidence"],
        "num_contexts": len(contexts),
        "retrieval_time_seconds": retrieval.metadata.get("retrieval_time_seconds", 0),
        "is_follow_up": is_follow_up,
        "standalone_query": std_log,
        "trace_id": trace_id,
    }
    response = QueryResponse(
        answer=answer,
        contexts=[ContextItem(**c) for c in contexts],
        metadata=meta,
        session_id=session_id,
        msg_id=msg_id,
    )
    return response, query_type, False


@track(name="rag-query-stream")
async def _run_stream_setup(svc: _Services, query_text: str, session_id: str, use_cache: bool) -> dict:
    observability.set_thread_id(session_id)
    prep = await _prepare(svc, query_text, session_id, use_cache)
    prep["trace_id"] = observability.current_trace_id()
    return prep


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging("DEBUG" if settings.debug else settings.log_level)
    observability.configure_opik(settings.opik_api_key, settings.opik_workspace, settings.opik_project_name)
    # Push generation templates to Opik's prompt library (D8 versioning/hot-swap) explicitly at
    # startup — guaranteed + logged, not a side-effect of whether the router happens to be built.
    from app.prompts import register_prompts

    register_prompts()  # no-op without Opik
    dogfood.set_enabled(settings.dogfood_enabled)
    logger.info("Starting FastPilot backend (debug=%s)", settings.debug)

    # Each getter degrades internally — construction never raises.
    app.state.pipeline = get_rag_pipeline()
    app.state.cache = get_semantic_cache()
    app.state.conversation = get_conversation_service()
    app.state.router = get_query_router()
    app.state.executor = get_executor()
    app.state.rate_limiter = RateLimiter(
        redis_client=getattr(app.state.conversation, "redis", None),
        per_minute=settings.playground_rate_per_min,
    )
    app.state.request_count = 0
    app.state.total_latency_ms = 0.0
    app.state.total_cost_usd = 0.0

    yield

    observability.flush()
    logger.info("Shutting down FastPilot backend")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------
def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title=settings.app_name, version="1.0.0", debug=settings.debug, lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):  # noqa: ANN202
        logger.exception("Unhandled error on %s", request.url.path)
        detail = str(exc) if settings.debug else "An unexpected error occurred"
        return JSONResponse(status_code=500, content={"error": "Internal server error", "detail": detail})

    @application.post("/query", response_model=QueryResponse, tags=["RAG"])
    async def query(request: QueryRequest, http: Request):  # noqa: ANN202
        start = time.time()
        svc = _Services(http.app)
        session_id = request.session_id or svc.conversation.create_session_id()

        safe, pattern = get_input_guard().check(request.query)
        if not safe:
            # Refusals are NOT written to conversation memory — otherwise the session
            # looks non-empty and the user's next genuine question is mis-treated as a
            # follow-up (a phantom rewrite against refusal-only history).
            logger.info("query refused session=%s pattern=%s", session_id[:14], pattern)
            return QueryResponse(
                answer=REFUSAL_MESSAGE,
                contexts=[],
                metadata={"refused": True, "guard_pattern": pattern, "cache_hit": False, "latency_ms": 0.0},
                session_id=session_id,
                msg_id=_new_msg_id(),
            )

        try:
            response, query_type, cache_hit = await _run_query(
                svc, http.app, request.query, session_id, request.use_cache, start
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Query failed")
            # Don't leak internals unless debugging (the global handler is bypassed by this raise).
            detail = f"Query failed: {exc}" if settings.debug else "Query processing failed — try again."
            raise HTTPException(status_code=503, detail=detail) from exc

        logger.info(
            "query done session=%s msg=%s type=%s cache_hit=%s latency_ms=%.0f",
            session_id[:14],
            response.msg_id,
            query_type,
            cache_hit,
            response.metadata["latency_ms"],
        )
        return response

    @application.post("/query/stream", tags=["RAG"])
    async def query_stream(request: QueryRequest, http: Request):  # noqa: ANN202
        svc = _Services(http.app)
        app_ref = http.app

        async def gen():
            start = time.time()
            session_id = request.session_id or svc.conversation.create_session_id()
            producer = None
            yield _sse("session", {"session_id": session_id})

            safe, pattern = get_input_guard().check(request.query)
            if not safe:
                msg_id = _new_msg_id()  # refusals stay out of conversation memory (see /query)
                for chunk in _stream_text_chunks(REFUSAL_MESSAGE):
                    yield _sse("token", {"token": chunk})
                    await asyncio.sleep(0.01)
                yield _sse(
                    "done", {"refused": True, "guard_pattern": pattern, "msg_id": msg_id, "session_id": session_id}
                )
                logger.info("stream refused session=%s pattern=%s", session_id[:14], pattern)
                return

            try:
                setup = await _run_stream_setup(svc, request.query, session_id, request.use_cache)
                standalone = setup["standalone"]
                if setup["is_follow_up"]:
                    yield _sse("rewrite", {"original": request.query, "standalone": standalone})

                cached = setup.get("cached")
                if cached:
                    query_type = cached.get("query_type", "FACTUAL")
                    yield _sse("cache_status", {"cache_hit": True, "distance": cached.get("distance", 0)})
                    yield _sse("classification", {"category": query_type, "confidence": 1.0})
                    for ctx in cached["contexts"]:
                        yield _sse("context", ctx)
                    for chunk in _stream_text_chunks(cached["answer"]):
                        yield _sse("token", {"token": chunk})
                        await asyncio.sleep(0.02)
                    std_log = standalone if setup["is_follow_up"] else None
                    msg_id, latency_ms = await _finalize_turn(
                        svc,
                        app_ref,
                        session_id=session_id,
                        user_query=request.query,
                        answer=cached["answer"],
                        contexts=cached["contexts"],
                        query_type=query_type,
                        cache_hit=True,
                        standalone_query=std_log,
                        start=start,
                        cost=0.0,
                    )
                    yield _sse(
                        "done",
                        {
                            "cache_hit": True,
                            "latency_ms": latency_ms,
                            "cost_usd": 0.0,
                            "query_type": query_type,
                            "msg_id": msg_id,
                            "session_id": session_id,
                            "trace_id": setup.get("trace_id"),
                        },
                    )
                    logger.info(
                        "stream done session=%s msg=%s cache_hit=True latency_ms=%.0f",
                        session_id[:14],
                        msg_id,
                        latency_ms,
                    )
                    return

                classification = setup["classification"]
                retrieval = setup["retrieval"]
                query_type = classification["category"]
                yield _sse("cache_status", {"cache_hit": False})
                yield _sse("classification", classification)

                contexts = _format_contexts(retrieval.contexts)
                for ctx in contexts:
                    yield _sse("context", ctx)
                    await asyncio.sleep(0.01)

                queue = await svc.pipeline.generate_stream(standalone, retrieval.contexts, setup["prompt_messages"])
                producer = getattr(queue, "task", None)
                while True:
                    token = await queue.get()
                    if token is None:
                        break
                    if await http.is_disconnected():
                        break
                    yield _sse("token", {"token": token})

                answer = getattr(queue, "full_answer", "")
                stream_error = getattr(queue, "stream_error", None)
                fallback_used = getattr(queue, "fallback_used", False)
                if stream_error:
                    yield _sse("error", {"error": str(stream_error)})
                    yield _sse("done", {"error": True, "session_id": session_id})
                    logger.warning("stream generation failed session=%s: %s", session_id[:14], str(stream_error)[:120])
                    return

                observability.update_trace_output(setup.get("trace_id"), {"answer": answer})
                if request.use_cache and answer:
                    await _cache_set(svc.cache, standalone, answer, contexts, query_type, setup.get("query_embedding"))
                cost = _estimate_cost(2)
                std_log = standalone if setup["is_follow_up"] else None
                msg_id, latency_ms = await _finalize_turn(
                    svc,
                    app_ref,
                    session_id=session_id,
                    user_query=request.query,
                    answer=answer,
                    contexts=contexts,
                    query_type=query_type,
                    cache_hit=False,
                    standalone_query=std_log,
                    start=start,
                    cost=cost,
                    fallback_used=fallback_used,
                )
                yield _sse(
                    "done",
                    {
                        "cache_hit": False,
                        "latency_ms": latency_ms,
                        "cost_usd": cost,
                        "query_type": query_type,
                        "fallback_used": fallback_used,
                        "msg_id": msg_id,
                        "session_id": session_id,
                        "num_contexts": len(contexts),
                        "trace_id": setup.get("trace_id"),
                    },
                )
                logger.info(
                    "stream done session=%s msg=%s type=%s cache_hit=False latency_ms=%.0f",
                    session_id[:14],
                    msg_id,
                    query_type,
                    latency_ms,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Stream failed")
                yield _sse("error", {"error": str(exc) if settings.debug else "Stream failed"})
            finally:
                # If the client disconnected mid-stream, stop the background generator
                # so it doesn't keep calling Gemini into an orphaned queue.
                if producer is not None and not producer.done():
                    producer.cancel()

        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @application.post("/agent/stream", tags=["Agent"])
    async def agent_stream(request: AgentRequest, http: Request):  # noqa: ANN202
        svc = _Services(http.app)
        executor = http.app.state.executor
        session_id = request.session_id or svc.conversation.create_session_id()

        async def gen():
            observability.set_thread_id(session_id)
            yield _sse("session", {"session_id": session_id})
            msg_id = _new_msg_id()
            orch = AgentOrchestrator(pipeline=svc.pipeline, executor=executor, budget_s=settings.agent_budget_s)
            answer_parts: list[str] = []
            success = False
            try:
                async for ev in orch.run(request.task):
                    if ev["event"] == "token":
                        answer_parts.append(ev["data"]["token"])
                    elif ev["event"] == "done":
                        success = bool(ev["data"].get("success"))
                        ev["data"].update({"msg_id": msg_id, "session_id": session_id})
                    yield _sse(ev["event"], ev["data"])
            except Exception as exc:  # noqa: BLE001
                logger.exception("Agent run failed")
                yield _sse("error", {"error": str(exc) if settings.debug else "Agent run failed"})
                return
            dogfood.log_interaction(
                session_id=session_id,
                msg_id=msg_id,
                mode="agent",
                query=request.task,
                answer="".join(answer_parts),
                contexts=[],
                cache_hit=False,
                query_type="CODE_GENERATION",
                latency_ms=0.0,
            )
            logger.info("agent done session=%s msg=%s success=%s", session_id[:14], msg_id, success)

        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @application.post("/execute", response_model=ExecuteResult, tags=["Playground"])
    async def execute(request: ExecuteRequest, http: Request):  # noqa: ANN202
        if not settings.playground_enabled:
            raise HTTPException(status_code=404, detail="Playground is disabled.")
        if len(request.code.encode("utf-8")) > settings.playground_max_code_bytes:
            return ExecuteResult(guard="oversize", stderr="That's a lot of code — the sandbox takes up to 10 KB.")
        allowed, retry = http.app.state.rate_limiter.check(request.session_id)
        if not allowed:
            return ExecuteResult(
                guard="rate_limit",
                stderr=(
                    "Easy there — 3 runs a minute keeps the sandbox happy. "
                    f"Your next run unlocks in {retry} seconds."
                ),
            )
        result = await asyncio.to_thread(http.app.state.executor.run, request.code)
        if result.blocked:
            return ExecuteResult(
                guard="denylist",
                exit_code=result.exit_code,
                stderr="That code uses something the sandbox doesn't allow (like network or subprocess calls). "
                "Stick to fastapi, pydantic, and the standard library.",
            )
        logger.info(
            "execute session=%s exit=%s dur=%dms",
            (request.session_id or "anon")[:14],
            result.exit_code,
            result.duration_ms,
        )
        return ExecuteResult(
            ok=result.ok,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_ms=result.duration_ms,
        )

    @application.post("/fix", response_model=FixResponse, tags=["Playground"])
    async def fix(request: FixRequest, http: Request):  # noqa: ANN202
        if not settings.playground_enabled:
            raise HTTPException(status_code=404, detail="Playground is disabled.")
        allowed, _ = http.app.state.rate_limiter.check(request.session_id)
        if not allowed:
            return FixResponse(fixed_code=request.code, guard="rate_limit")
        pipe = http.app.state.pipeline
        if not pipe.is_healthy():
            raise HTTPException(status_code=503, detail="Code model unavailable.")
        from haystack.dataclasses import ChatMessage

        from app.prompts import AGENT_FIX_PROMPT

        user = (
            f"TASK: fix this FastAPI code so it runs.\n\nPREVIOUS CODE:\n{request.code}\n\n"
            f"TRACEBACK / STDERR:\n{request.stderr}\n\nCONTEXT:\n(none — fix from the traceback)"
        )
        messages = [ChatMessage.from_system(AGENT_FIX_PROMPT), ChatMessage.from_user(user)]
        raw = await pipe.generate(user, [], messages)
        return FixResponse(fixed_code=extract_code(raw))

    @application.post("/feedback", response_model=FeedbackResponse, tags=["Feedback"])
    async def feedback(request: FeedbackRequest):  # noqa: ANN202
        meta = request.metadata or {}
        trace_id = meta.get("trace_id", "")
        observability.log_feedback_score(trace_id, request.rating, request.comment, meta.get("reason", ""))
        dogfood.log_feedback(
            msg_id=request.msg_id, rating=request.rating, comment=request.comment, reason=meta.get("reason", "")
        )
        logger.info("feedback msg=%s rating=%s", request.msg_id, request.rating)
        return FeedbackResponse(status="stored", feedback_key=trace_id or request.msg_id)

    @application.get("/conversation/{session_id}", response_model=ConversationResponse, tags=["Conversation"])
    async def conversation(session_id: str, http: Request):  # noqa: ANN202
        conv = http.app.state.conversation
        messages = await asyncio.to_thread(conv.get_history, session_id)
        info = await asyncio.to_thread(conv.get_session_info, session_id)
        return ConversationResponse(
            session_id=session_id,
            messages=[ConversationMessage(**m) for m in messages],
            session_info=info,
        )

    @application.get("/health", response_model=HealthResponse, tags=["Monitoring"])
    async def health(http: Request):  # noqa: ANN202
        svc = _Services(http.app)
        comps = {
            "rag_pipeline": "healthy" if svc.pipeline.is_healthy() else "degraded",
            "semantic_cache": "healthy" if svc.cache.is_healthy() else "degraded",
            "conversation": "healthy" if svc.conversation.is_healthy() else "degraded",
        }
        status = "healthy" if all(v == "healthy" for v in comps.values()) else "degraded"
        return HealthResponse(status=status, components=comps)

    @application.get("/metrics", response_model=MetricsResponse, tags=["Monitoring"])
    async def metrics(http: Request):  # noqa: ANN202
        app_ref = http.app
        n = app_ref.state.request_count
        return MetricsResponse(
            total_requests=n,
            avg_latency_ms=round(app_ref.state.total_latency_ms / n, 2) if n else 0.0,
            total_cost_usd=round(app_ref.state.total_cost_usd, 4),
            cache_stats=app_ref.state.cache.get_stats(),
        )

    @application.get("/", tags=["General"])
    async def root():  # noqa: ANN202
        return {
            "name": settings.app_name,
            "tagline": "Learn FastAPI, fast.",
            "version": "1.0.0",
            "endpoints": ["/query", "/query/stream", "/feedback", "/conversation/{id}", "/health", "/metrics"],
        }

    return application


app = create_app()
