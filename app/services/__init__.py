"""Production service layer — lazy singletons reached through getters.

Tests monkeypatch in exactly one place: call ``set_services(...)`` to inject fakes
before building the app, or ``reset_services()`` to clear them. This is why the app
always reaches services via these getters, never via module-level instances.

Service classes are imported lazily *inside* the getters so importing this package
(or a single submodule, e.g. ``app.services.semantic_cache`` from a setup script)
doesn't drag in the heavy Haystack stack that only ``rag_pipeline`` needs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:  # type hints only — no runtime import cost
    from app.services.conversation import ConversationService
    from app.services.query_router import QueryRouter
    from app.services.rag_pipeline import ProductionRAGPipeline
    from app.services.semantic_cache import SemanticCache

_rag: Optional["ProductionRAGPipeline"] = None
_cache: Optional["SemanticCache"] = None
_conversation: Optional["ConversationService"] = None
_router: Optional["QueryRouter"] = None


def get_rag_pipeline() -> "ProductionRAGPipeline":
    global _rag
    if _rag is None:
        from app.services.rag_pipeline import ProductionRAGPipeline

        _rag = ProductionRAGPipeline()
    return _rag


def get_semantic_cache() -> "SemanticCache":
    global _cache
    if _cache is None:
        from app.services.semantic_cache import SemanticCache

        _cache = SemanticCache()
    return _cache


def get_conversation_service() -> "ConversationService":
    global _conversation
    if _conversation is None:
        from app.services.conversation import ConversationService

        _conversation = ConversationService()
    return _conversation


def get_query_router() -> "QueryRouter":
    global _router
    if _router is None:
        from app.services.query_router import QueryRouter

        _router = QueryRouter()
    return _router


def set_services(
    *,
    rag: Any = None,
    cache: Any = None,
    conversation: Any = None,
    router: Any = None,
) -> None:
    """Inject service instances (tests). Only the provided ones are replaced."""
    global _rag, _cache, _conversation, _router
    if rag is not None:
        _rag = rag
    if cache is not None:
        _cache = cache
    if conversation is not None:
        _conversation = conversation
    if router is not None:
        _router = router


def reset_services() -> None:
    """Clear all singletons (tests)."""
    global _rag, _cache, _conversation, _router
    _rag = _cache = _conversation = _router = None


__all__ = [
    "get_rag_pipeline",
    "get_semantic_cache",
    "get_conversation_service",
    "get_query_router",
    "set_services",
    "reset_services",
]
