"""Stub backend for the Playwright visual tests.

A standalone FastAPI app that returns canned, deterministic responses for every
endpoint the frontend hits — no LLM, no Redis, no Qdrant. The Streamlit UI talks to
this (``API_BASE_URL`` points here) so the visual harness can render real content
hermetically. The agent stream deliberately fails attempt 1 and passes attempt 2 so
the timeline shows the ✗→✓ self-correction money shot.

Run standalone:
    uvicorn stub_backend:app --app-dir final-submission/tests/visual --port 8999
"""

from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI(title="FastPilot stub backend")

_CONTEXTS = [
    {
        "rank": 1,
        "score": 0.91,
        "content": (
            "from fastapi.security import OAuth2PasswordBearer\noauth2_scheme = OAuth2PasswordBearer(tokenUrl='token')"
        ),
        "metadata": {"file_path": "docs/tutorial/security/oauth2-jwt.md", "category": "docs", "file_type": "markdown"},
    },
    {
        "rank": 2,
        "score": 0.84,
        "content": "Use python-jose to create and verify the JWT access token with an expiry.",
        "metadata": {
            "file_path": "full-stack-template/app/core/security.py",
            "category": "code",
            "file_type": "python",
        },
    },
]
_ANSWER = (
    "To add JWT authentication, create an `OAuth2PasswordBearer` scheme [1] and verify the token "
    "in a dependency. Issue tokens with an expiry using python-jose, as the template's `security.py` shows [2]."
)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "components": {"rag_pipeline": "healthy", "semantic_cache": "healthy", "conversation": "healthy"},
    }


@app.post("/query")
def query(body: dict):
    return {
        "answer": _ANSWER,
        "contexts": _CONTEXTS,
        "metadata": {"cache_hit": False, "latency_ms": 8200.0, "cost_usd": 0.0032, "query_type": "HOW_TO"},
        "session_id": body.get("session_id") or "sess_demo",
        "msg_id": "msg_demo",
    }


@app.post("/query/stream")
async def query_stream(body: dict, req: Request):
    async def gen():
        yield _sse("session", {"session_id": body.get("session_id") or "sess_demo"})
        yield _sse("cache_status", {"cache_hit": False})
        yield _sse("classification", {"category": "HOW_TO", "confidence": 0.97})
        for ctx in _CONTEXTS:
            yield _sse("context", ctx)
        for word in _ANSWER.split(" "):
            yield _sse("token", {"token": word + " "})
            await asyncio.sleep(0.005)
        yield _sse(
            "done",
            {
                "cache_hit": False,
                "latency_ms": 8200.0,
                "cost_usd": 0.0032,
                "query_type": "HOW_TO",
                "msg_id": "msg_demo",
                "session_id": "sess_demo",
                "num_contexts": 2,
            },
        )

    return StreamingResponse(gen(), media_type="text/event-stream")


_AGENT_CODE_1 = (
    "from fastapi import FastAPI\nfrom fastapi.testclient import TestClient\n"
    "# missing the 422 assertion\napp = FastAPI()"
)
_AGENT_CODE_2 = (
    "from fastapi import FastAPI\n"
    "from fastapi.testclient import TestClient\n"
    "from pydantic import BaseModel, Field  # validate with Pydantic [1]\n\n"
    "class User(BaseModel):\n    name: str\n    age: int = Field(gt=0)\n\n"
    "app = FastAPI()\n\n@app.post('/users')\ndef create(u: User):\n    return u\n\n"
    "client = TestClient(app)\n"
    "print('valid:', client.post('/users', json={'name':'Ada','age':36}).status_code)\n"
    "print('invalid:', client.post('/users', json={'name':'Ada','age':-1}).status_code)\n"
    "assert client.post('/users', json={'name':'Ada','age':-1}).status_code == 422\n"
)


@app.post("/agent/stream")
async def agent_stream(body: dict):
    async def gen():
        yield _sse("session", {"session_id": "sess_demo"})
        yield _sse("agent_step", {"name": "plan", "status": "running"})
        await asyncio.sleep(0.05)
        yield _sse("agent_step", {"name": "plan", "status": "done", "detail": "validate a payload, assert 422"})
        yield _sse("agent_step", {"name": "retrieve", "status": "running"})
        for ctx in _CONTEXTS:
            yield _sse("context", ctx)
        yield _sse("agent_step", {"name": "retrieve", "status": "done", "detail": "2 sources"})
        # Attempt 1 fails.
        yield _sse("agent_step", {"name": "write", "status": "running", "detail": "attempt 1"})
        yield _sse("code", {"attempt": 1, "content": _AGENT_CODE_1})
        yield _sse("agent_step", {"name": "write", "status": "done", "detail": "attempt 1"})
        yield _sse("agent_step", {"name": "run", "status": "running", "detail": "attempt 1"})
        yield _sse(
            "exec_result",
            {
                "attempt": 1,
                "exit_code": 1,
                "stdout": "",
                "stderr": "AssertionError: expected 422, got 200",
                "duration_ms": 540,
            },
        )
        yield _sse("agent_step", {"name": "run", "status": "error", "detail": "AssertionError · line 24"})
        # Attempt 2 fixes it.
        yield _sse("agent_step", {"name": "fix", "status": "running", "detail": "attempt 2"})
        yield _sse("code", {"attempt": 2, "content": _AGENT_CODE_2})
        yield _sse("agent_step", {"name": "fix", "status": "done", "detail": "attempt 2"})
        yield _sse("agent_step", {"name": "run", "status": "running", "detail": "attempt 2"})
        yield _sse(
            "exec_result",
            {"attempt": 2, "exit_code": 0, "stdout": "valid: 200\ninvalid: 422", "stderr": "", "duration_ms": 3100},
        )
        yield _sse("agent_step", {"name": "run", "status": "done", "detail": "exit 0"})
        for (
            word
        ) in "The endpoint validates the payload with Pydantic [1]; invalid input returns 422 automatically.".split(
            " "
        ):
            yield _sse("token", {"token": word + " "})
        yield _sse(
            "done",
            {"success": True, "attempts": 2, "num_contexts": 2, "msg_id": "msg_agent", "session_id": "sess_demo"},
        )

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/execute")
def execute(body: dict):
    return {
        "ok": True,
        "exit_code": 0,
        "stdout": "valid: 200\ninvalid: 422",
        "stderr": "",
        "duration_ms": 2400,
        "guard": None,
    }


@app.post("/fix")
def fix(body: dict):
    return {"fixed_code": body.get("code", "") + "\n# fixed", "guard": None}


@app.post("/feedback")
def feedback(body: dict):
    return {"status": "stored", "feedback_key": "msg_demo"}


@app.get("/conversation/{session_id}")
def conversation(session_id: str):
    return {"session_id": session_id, "messages": [], "session_info": None}
