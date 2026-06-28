"""Agent orchestrator (Week-6 augmentation) — grounded code-runner.

Deterministic, code-driven loop (mirrors the class CRAG routing philosophy, not free
tool-calling): InputGuard → plan → retrieve (T1b) → write → AST-scan+sandbox run →
self-correct (≤2 fix attempts) → explain, or an honest failure. Every step is yielded
as an event the SSE endpoint relays, so the UI timeline updates live.

The loop is framework-light and fully unit-testable: inject a fake ``pipeline`` (with
``generate`` / ``retrieve`` / ``generate_stream``) and a fake ``executor``; production
wires the real RAG pipeline + ``SubprocessExecutor``.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator

from haystack.dataclasses import ChatMessage

from app.augmentations.security import REFUSAL_MESSAGE, OutputValidator, get_input_guard
from app.prompts import AGENT_CODE_PROMPT, AGENT_EXPLAIN_PROMPT, AGENT_FIX_PROMPT, AGENT_PLAN_PROMPT

logger = logging.getLogger(__name__)

_CODE_FENCE = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL)


def extract_code(text: str) -> str:
    """Pull the python out of a fenced block; fall back to the whole text."""
    m = _CODE_FENCE.search(text or "")
    return (m.group(1) if m else (text or "")).strip()


def _format_contexts(contexts: list) -> str:
    if not contexts:
        return "(no context retrieved)"
    parts = []
    for i, doc in enumerate(contexts, 1):
        path = doc.meta.get("file_path", doc.meta.get("source", "unknown"))
        parts.append(f"[{i}] (source: {path})\n{doc.content}")
    return "\n\n".join(parts)


class AgentOrchestrator:
    def __init__(
        self,
        *,
        pipeline,
        executor,
        output_validator: OutputValidator | None = None,
        max_fix_attempts: int = 2,
        budget_s: int = 90,
    ):
        self.pipeline = pipeline
        self.executor = executor
        self.guard = get_input_guard()
        self.validator = output_validator or OutputValidator()
        self.max_fix_attempts = max_fix_attempts
        self.budget_s = budget_s

    async def _complete(self, system: str, user: str) -> str:
        messages = [ChatMessage.from_system(system), ChatMessage.from_user(user)]
        return await self.pipeline.generate(user, [], messages)

    async def run(self, task: str) -> AsyncIterator[dict]:  # noqa: C901 - linear pipeline, reads top-to-bottom
        start = time.monotonic()

        safe, pattern = self.guard.check(task)
        if not safe:
            logger.info("agent refused pattern=%s", pattern)
            yield {"event": "token", "data": {"token": REFUSAL_MESSAGE}}
            yield {"event": "done", "data": {"success": False, "refused": True, "guard_pattern": pattern}}
            return

        if not getattr(self.pipeline, "ready", True):
            yield {"event": "agent_step", "data": {"name": "plan", "status": "error", "detail": "backend not ready"}}
            yield {"event": "done", "data": {"success": False, "error": True}}
            return

        # 1. Plan
        yield {"event": "agent_step", "data": {"name": "plan", "status": "running"}}
        plan = await self._complete(AGENT_PLAN_PROMPT, task)
        yield {"event": "agent_step", "data": {"name": "plan", "status": "done", "detail": plan[:280]}}

        # 2. Retrieve (same T1b pipeline as chat)
        yield {"event": "agent_step", "data": {"name": "retrieve", "status": "running"}}
        retrieval = await self.pipeline.retrieve(task)
        contexts = retrieval.contexts
        ctx_block = _format_contexts(contexts)
        for rank, doc in enumerate(contexts, 1):
            yield {
                "event": "context",
                "data": {
                    "rank": rank,
                    "score": round(doc.score, 4) if doc.score else 0.0,
                    "content": doc.content,
                    "metadata": {"file_path": doc.meta.get("file_path", "unknown")},
                },
            }
        yield {
            "event": "agent_step",
            "data": {"name": "retrieve", "status": "done", "detail": f"{len(contexts)} sources"},
        }

        # 3/4. Write → run → fix loop
        result = None
        code = ""
        attempts = 0
        total_attempts = self.max_fix_attempts + 1
        for attempt in range(1, total_attempts + 1):
            attempts = attempt
            if time.monotonic() - start > self.budget_s:
                yield {
                    "event": "agent_step",
                    "data": {"name": "run", "status": "error", "detail": "time budget reached"},
                }
                break

            step = "write" if attempt == 1 else "fix"
            yield {"event": "agent_step", "data": {"name": step, "status": "running", "detail": f"attempt {attempt}"}}
            if attempt == 1:
                raw = await self._complete(AGENT_CODE_PROMPT, f"TASK: {task}\n\nCONTEXT:\n{ctx_block}")
            else:
                raw = await self._complete(
                    AGENT_FIX_PROMPT,
                    f"TASK: {task}\n\nPREVIOUS CODE:\n{code}\n\n"
                    f"TRACEBACK / STDERR:\n{result.stderr}\n\nCONTEXT:\n{ctx_block}",
                )
            code = extract_code(raw)
            yield {"event": "code", "data": {"attempt": attempt, "content": code}}
            yield {"event": "agent_step", "data": {"name": step, "status": "done", "detail": f"attempt {attempt}"}}

            yield {"event": "agent_step", "data": {"name": "run", "status": "running", "detail": f"attempt {attempt}"}}
            result = await asyncio.to_thread(self.executor.run, code)
            yield {
                "event": "exec_result",
                "data": {
                    "attempt": attempt,
                    "ok": result.ok,
                    "exit_code": result.exit_code,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "duration_ms": result.duration_ms,
                    "blocked": result.blocked,
                },
            }
            if result.ok:
                yield {"event": "agent_step", "data": {"name": "run", "status": "done", "detail": "exit 0"}}
                break
            detail = result.block_reason or (f"exit {result.exit_code}" if not result.timed_out else "timed out")
            yield {"event": "agent_step", "data": {"name": "run", "status": "error", "detail": detail}}

        success = bool(result and result.ok)

        # 5. Explain (success) or honest failure
        if success:
            explain_user = f"TASK: {task}\n\nCODE:\n{code}\n\nRUN OUTPUT:\n{result.stdout}\n\nCONTEXT:\n{ctx_block}"
            async for tok in self._stream_explanation(explain_user):
                clean, _ = self.validator.redact(tok)
                yield {"event": "token", "data": {"token": clean}}
        else:
            last = (result.stderr if result else "no result")[:600]
            msg = (
                f"I couldn't get this running within {attempts} attempt(s). "
                f"The last error was:\n\n```\n{last}\n```\n\n"
                "The retrieved sources above show the relevant FastAPI patterns to try next."
            )
            for chunk in msg.split(" "):
                yield {"event": "token", "data": {"token": chunk + " "}}

        yield {
            "event": "done",
            "data": {"success": success, "attempts": attempts, "num_contexts": len(contexts)},
        }

    async def _stream_explanation(self, user: str) -> AsyncIterator[str]:
        messages = [ChatMessage.from_system(AGENT_EXPLAIN_PROMPT), ChatMessage.from_user(user)]
        queue = await self.pipeline.generate_stream(user, [], messages)
        while True:
            tok = await queue.get()
            if tok is None:
                break
            yield tok
