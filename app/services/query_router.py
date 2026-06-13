"""Query router — classification + type-specific prompt building.

``classify`` makes one Gemini call to bucket the query into FACTUAL / HOW_TO /
TROUBLESHOOTING / CODE_GENERATION (FastAPI-domain few-shots live in the prompt).
``build_prompt`` formats contexts as ``[n] (source: path, type)`` for inline
citations and fetches the latest template from Opik (hot-swap), linking the prompt
version to the trace. Classification falls back to FACTUAL whenever the LLM is
unavailable or returns junk.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from haystack import Document
from haystack.dataclasses import ChatMessage

from app.config import get_settings
from app.formatting import source_label
from app.observability import link_prompt_to_trace, track, update_current_span
from app.prompts import (
    CLASSIFICATION_PROMPT,
    DEFAULT_QUERY_TYPE,
    QUERY_TYPES,
    fetch_prompt,
)

logger = logging.getLogger(__name__)


class QueryRouter:
    def __init__(self, *, llm: Any = None):
        s = get_settings()
        self._model = s.llm_model
        self._google_key = s.google_api_key
        self._llm = llm
        self._llm_built = llm is not None
        # Prompt registration happens once at app startup (see main.lifespan), not per router build.

    def _get_llm(self) -> Any:
        if not self._llm_built:
            self._llm_built = True
            if self._google_key:
                try:
                    from haystack_integrations.components.generators.google_genai import (
                        GoogleGenAIChatGenerator,
                    )

                    self._llm = GoogleGenAIChatGenerator(model=self._model)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Classifier LLM unavailable: %s", str(exc)[:120])
                    self._llm = None
            else:
                self._llm = None
        return self._llm

    @track(name="classify")
    async def classify(self, query: str) -> dict[str, Any]:
        llm = self._get_llm()
        if llm is None:
            return {"category": DEFAULT_QUERY_TYPE, "confidence": 0.0}

        messages = [
            ChatMessage.from_system(CLASSIFICATION_PROMPT),
            ChatMessage.from_user(query),
        ]
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, lambda: llm.run(messages=messages))
            parsed = self._parse_json(result["replies"][0].text.strip())
            category = str(parsed.get("category", DEFAULT_QUERY_TYPE)).upper()
            confidence = float(parsed.get("confidence", 0.5))
            if category not in QUERY_TYPES:
                category, confidence = DEFAULT_QUERY_TYPE, 0.0
            return {"category": category, "confidence": confidence}
        except Exception as exc:  # noqa: BLE001 - default on any failure
            logger.debug("Classification failed, defaulting to %s: %s", DEFAULT_QUERY_TYPE, str(exc)[:120])
            update_current_span(metadata={"classification_error": str(exc)[:200]})
            return {"category": DEFAULT_QUERY_TYPE, "confidence": 0.0}

    def build_prompt(self, query: str, contexts: list[Document], query_type: str) -> list[ChatMessage]:
        system_prompt, prompt_obj = fetch_prompt(query_type)
        link_prompt_to_trace(prompt_obj)
        return [
            ChatMessage.from_system(system_prompt),
            ChatMessage.from_user(f"CONTEXT:\n{self._format_contexts(contexts)}\n\nQUESTION: {query}"),
        ]

    @staticmethod
    def _format_contexts(contexts: list[Document]) -> str:
        if not contexts:
            return "(No relevant context found.)"
        parts = []
        for i, doc in enumerate(contexts, 1):
            src = source_label(doc.meta)
            category = doc.meta.get("category", doc.meta.get("source", doc.meta.get("file_type", "unknown")))
            parts.append(f"[{i}] (source: {src}, type: {category})\n{doc.content}")
        return "\n\n".join(parts)

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = "\n".join(ln for ln in cleaned.split("\n") if not ln.strip().startswith("```")).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            start, end = cleaned.find("{"), cleaned.rfind("}") + 1
            if 0 <= start < end:
                try:
                    return json.loads(cleaned[start:end])
                except json.JSONDecodeError:
                    pass
            return {}

    def is_healthy(self) -> bool:
        return self._get_llm() is not None
