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


# --- Conversation ---
class ConversationMessage(BaseModel):
    msg_id: str
    role: str  # "user" | "assistant"
    content: str
    timestamp: float
    metadata: Optional[dict[str, Any]] = None


class ConversationResponse(BaseModel):
    session_id: str
    messages: list[ConversationMessage] = Field(default_factory=list)
    session_info: Optional[dict[str, Any]] = None


# --- Health / metrics ---
class HealthResponse(BaseModel):
    status: str  # "healthy" | "degraded"
    components: dict[str, str] = Field(default_factory=dict)


class MetricsResponse(BaseModel):
    total_requests: int = 0
    avg_latency_ms: float = 0.0
    total_cost_usd: float = 0.0
    cache_stats: dict[str, Any] = Field(default_factory=dict)


# --- Agent / Playground (Phase 3) ---
class AgentRequest(BaseModel):
    task: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[str] = None


class ExecuteRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=100_000)  # hard cap; 10KB soft-guard in handler
    session_id: str = ""


class ExecuteResult(BaseModel):
    ok: bool = False
    exit_code: int = -1
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    guard: Optional[str] = None  # "oversize" | "rate_limit" | "denylist" | None


class FixRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=100_000)
    stderr: str = ""
    session_id: str = ""


class FixResponse(BaseModel):
    fixed_code: str
    guard: Optional[str] = None
