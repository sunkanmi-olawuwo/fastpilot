"""Conversation memory — Redis sliding window + conditional query rewriting.

Stores the last N messages per session (LIST + LTRIM) with a sliding TTL, and
rewrites follow-up questions into standalone queries with a single LLM call —
skipping the call entirely on the first turn (no history = no rewrite).

Graceful degradation (D4 / AC1.5): if Redis is unreachable the service keeps
working from a per-process in-memory dict — memory survives within the process,
``is_healthy`` reports False, and nothing 5xxes. The rewriter is built only when a
Google key is present; without it, follow-ups pass through unrewritten.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict, deque
from typing import TYPE_CHECKING, Any, Optional

from app.config import get_settings
from app.observability import track, update_current_span
from app.prompts import REWRITE_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import redis

SESSION_PREFIX = "chat:"


class ConversationService:
    def __init__(self, *, redis_client: Optional["redis.Redis"] = None, rewriter: Any = None):
        s = get_settings()
        self.window_size = s.conversation_window_size
        self.session_ttl = s.conversation_session_ttl
        self._model = s.llm_model
        self._google_key = s.google_api_key

        self.redis = None
        self.degraded = False
        self._mem: dict[str, deque] = defaultdict(lambda: deque(maxlen=self.window_size))
        self._mem_meta: dict[str, dict] = defaultdict(dict)

        if redis_client is not None:
            self.redis = redis_client  # injected (tests use fakeredis)
        else:
            try:
                from app.redis_client import make_redis_client

                self.redis = make_redis_client(s, decode_responses=True)  # JSON strings only
                self.redis.ping()
                logger.info("Conversation memory ready (window=%d, ttl=%ds)", self.window_size, self.session_ttl)
            except Exception as exc:  # noqa: BLE001 - degrade to in-memory
                logger.warning("Redis down — conversation memory in-process only (degraded): %s", str(exc)[:160])
                self.redis = None
                self.degraded = True

        # Rewriter LLM (built lazily; injected in tests).
        self._rewriter = rewriter
        self._rewriter_built = rewriter is not None

    # -- rewriter -----------------------------------------------------------
    def _get_rewriter(self) -> Any:
        if not self._rewriter_built:
            self._rewriter_built = True
            if self._google_key:
                try:
                    from haystack_integrations.components.generators.google_genai import (
                        GoogleGenAIChatGenerator,
                    )

                    self._rewriter = GoogleGenAIChatGenerator(model=self._model)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Rewriter unavailable: %s", str(exc)[:120])
                    self._rewriter = None
            else:
                self._rewriter = None
        return self._rewriter

    # -- sessions -----------------------------------------------------------
    @staticmethod
    def create_session_id() -> str:
        return f"sess_{uuid.uuid4().hex}"

    def _demote(self, exc: Exception) -> None:
        """Flip to in-memory after a *runtime* Redis failure (symmetric with the
        cache's no-op degradation), so a mid-session outage never 5xxes — AC1.5."""
        if not self.degraded:
            logger.warning("Redis failed at runtime — conversation now in-memory: %s", str(exc)[:160])
        self.redis = None
        self.degraded = True

    def get_history(self, session_id: str) -> list[dict[str, Any]]:
        if self.redis is not None:
            try:
                key = f"{SESSION_PREFIX}{session_id}:messages"
                raw = self.redis.lrange(key, 0, -1)
                if raw:
                    self.redis.expire(key, self.session_ttl)
                return [json.loads(r) for r in raw]
            except Exception as exc:  # noqa: BLE001 - degrade, never 5xx
                self._demote(exc)
        return list(self._mem.get(session_id, []))

    def add_message(self, session_id: str, role: str, content: str, metadata: Optional[dict[str, Any]] = None) -> str:
        msg_id = f"msg_{uuid.uuid4().hex[:12]}"
        message = {"msg_id": msg_id, "role": role, "content": content, "timestamp": time.time()}
        if metadata:
            message["metadata"] = metadata

        if self.redis is not None:
            try:
                key = f"{SESSION_PREFIX}{session_id}:messages"
                meta_key = f"{SESSION_PREFIX}{session_id}:meta"
                pipe = self.redis.pipeline()
                pipe.rpush(key, json.dumps(message))
                pipe.ltrim(key, -self.window_size, -1)
                pipe.expire(key, self.session_ttl)
                pipe.hsetnx(meta_key, "created_at", str(time.time()))
                pipe.hset(meta_key, "last_active", str(time.time()))
                pipe.hincrby(meta_key, "total_messages", 1)
                pipe.expire(meta_key, self.session_ttl)
                pipe.execute()
                return msg_id
            except Exception as exc:  # noqa: BLE001 - degrade, never 5xx
                self._demote(exc)

        self._mem[session_id].append(message)
        meta = self._mem_meta[session_id]
        meta.setdefault("created_at", time.time())
        meta["last_active"] = time.time()
        meta["total_messages"] = meta.get("total_messages", 0) + 1
        return msg_id

    def get_session_info(self, session_id: str) -> Optional[dict[str, Any]]:
        if self.redis is not None:
            try:
                meta = self.redis.hgetall(f"{SESSION_PREFIX}{session_id}:meta")
                if not meta:
                    return None
                return {
                    "session_id": session_id,
                    "created_at": float(meta.get("created_at", 0)),
                    "last_active": float(meta.get("last_active", 0)),
                    "total_messages": int(meta.get("total_messages", 0)),
                }
            except Exception as exc:  # noqa: BLE001 - degrade, never 5xx
                self._demote(exc)
        meta = self._mem_meta.get(session_id)
        return {"session_id": session_id, **meta} if meta else None

    # -- rewriting ----------------------------------------------------------
    @track(name="rewrite_if_needed")
    async def rewrite_if_needed(self, query: str, session_id: str) -> dict[str, Any]:
        history = await asyncio.to_thread(self.get_history, session_id)
        if not history:
            return {
                "original_query": query,
                "standalone_query": query,
                "is_follow_up": False,
                "history_length": 0,
            }
        try:
            standalone = await self._rewrite_query(query, history)
            return {
                "original_query": query,
                "standalone_query": standalone,
                "is_follow_up": True,
                "history_length": len(history),
            }
        except Exception as exc:  # noqa: BLE001 - rewrite failure is non-fatal
            logger.debug("Query rewrite failed, using original: %s", str(exc)[:120])
            update_current_span(metadata={"rewrite_error": str(exc)[:200], "fell_back_to_original": True})
            return {
                "original_query": query,
                "standalone_query": query,
                "is_follow_up": True,
                "history_length": len(history),
            }

    async def _rewrite_query(self, query: str, history: list[dict[str, Any]]) -> str:
        rewriter = self._get_rewriter()
        if rewriter is None:
            return query  # no LLM available — pass through

        from haystack.dataclasses import ChatMessage

        history_text = "".join(f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}\n" for m in history)
        messages = [
            ChatMessage.from_system(REWRITE_SYSTEM_PROMPT),
            ChatMessage.from_user(
                f"Chat History:\n{history_text}\n"
                f"Latest Question: {query}\n\n"
                f"Rewrite the latest question as a standalone question:"
            ),
        ]
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, lambda: rewriter.run(messages=messages))
        standalone = result["replies"][0].text.strip()
        return standalone or query

    def is_healthy(self) -> bool:
        if self.redis is None:
            return False
        try:
            self.redis.ping()
            return True
        except Exception:  # noqa: BLE001
            return False
