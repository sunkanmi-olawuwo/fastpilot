"""Request/response schemas — the single source of truth shared by the backend
and the frontend SSE parser (plan §10.2, the SSE contract round-trip test).

Phase 0 defines the core contract; later phases add agent/playground payloads.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# --- Query ---
class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[str] = None
    use_cache: bool = True


class ContextItem(BaseModel):
    rank: int
    score: float
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class QueryResponse(BaseModel):
    answer: str
    contexts: list[ContextItem] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    session_id: str
    msg_id: str


# --- Feedback ---
class FeedbackRequest(BaseModel):
    session_id: str
    msg_id: str
    rating: str  # "up" | "down"
    query: str = ""
    answer: str = ""
    comment: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class FeedbackResponse(BaseModel):
    status: str
    feedback_key: Optional[str] = None


# --- Health / metrics ---
class HealthResponse(BaseModel):
    status: str  # "healthy" | "degraded"
    components: dict[str, str] = Field(default_factory=dict)


class MetricsResponse(BaseModel):
    total_requests: int = 0
    avg_latency_ms: float = 0.0
    total_cost_usd: float = 0.0
    cache_stats: dict[str, Any] = Field(default_factory=dict)
