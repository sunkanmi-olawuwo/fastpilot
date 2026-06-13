"""Streamlit AppTest smoke (plan §6).

Drives the real ``app.py`` with ``api_client`` monkeypatched — no backend, no network.
AppTest executes the Python, not a browser, so CSS/responsiveness stays on the manual
device checklist (we say so rather than pretend it's covered). Skipped if Streamlit
isn't installed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

_APP = str(Path(__file__).resolve().parent.parent / "frontend" / "app.py")


def _streamed(prompt, session_id, use_cache):
    """A canned SSE stream standing in for api_client.stream_query."""
    yield "session", {"session_id": "sess_test"}
    yield "cache_status", {"cache_hit": False}
    yield "classification", {"category": "HOW_TO"}
    yield (
        "context",
        {
            "rank": 1,
            "content": "OAuth2PasswordBearer ...",
            "metadata": {"file_path": "docs/security.md", "category": "docs"},
        },
    )
    yield "token", {"token": "To add JWT auth, use OAuth2PasswordBearer [1]."}
    yield "done", {"msg_id": "msg_1", "latency_ms": 1200.0, "query_type": "HOW_TO", "cache_hit": False}


@pytest.fixture
def at(monkeypatch):
    import api_client

    monkeypatch.setattr(api_client, "stream_query", _streamed)
    monkeypatch.setattr(api_client, "send_feedback", lambda *a, **k: True)
    return AppTest.from_file(_APP, default_timeout=30)


def test_welcome_renders_chips(at):
    at.run()
    assert not at.exception
    labels = [b.label for b in at.button]
    assert any("Add JWT auth" in lbl for lbl in labels)
    assert any("Write & run" in lbl for lbl in labels)


def test_sending_query_appends_user_and_assistant(at):
    at.run()
    at.chat_input[0].set_value("How do I add JWT auth?").run()
    roles = [m["role"] for m in at.session_state["messages"]]
    assert roles == ["user", "assistant"]
    assert "OAuth2PasswordBearer" in at.session_state["messages"][1]["content"]
    assert at.session_state["messages"][1]["metadata"]["query_type"] == "HOW_TO"


def _streamed_followup(prompt, session_id, use_cache):
    """A follow-up turn: the backend rewrote the query, so a `rewrite` event carries the
    standalone and `done` echoes it in metadata."""
    standalone = "Can a query parameter with a default value be an integer?"
    yield "session", {"session_id": "sess_test"}
    yield "rewrite", {"original": prompt, "standalone": standalone}
    yield "cache_status", {"cache_hit": False}
    yield "classification", {"category": "FACTUAL"}
    yield "token", {"token": "Yes — annotate the parameter as `int` [1]."}
    yield "done", {"msg_id": "m", "latency_ms": 900.0, "query_type": "FACTUAL", "standalone_query": standalone}


def test_rewrite_caption_shows_standalone_query(monkeypatch):
    """A follow-up shows the '↻ searched as: <standalone>' caption (the rewrite text)."""
    import api_client

    monkeypatch.setattr(api_client, "stream_query", _streamed_followup)
    monkeypatch.setattr(api_client, "send_feedback", lambda *a, **k: True)
    at = AppTest.from_file(_APP, default_timeout=30)
    at.run()
    at.chat_input[0].set_value("can it be an integer?").run()
    msg = at.session_state["messages"][1]
    assert msg["metadata"]["standalone_query"] == "Can a query parameter with a default value be an integer?"
    assert any("searched as" in str(m.value) and "integer" in str(m.value) for m in at.markdown)


def _streamed_lowconf(prompt, session_id, use_cache):
    """An off-corpus query: the best reranked chunk scored below the floor, so `done`
    carries low_confidence (the rerank-confidence guard fired)."""
    yield "session", {"session_id": "s"}
    yield "cache_status", {"cache_hit": False}
    yield "classification", {"category": "FACTUAL"}
    yield "token", {"token": "Here is a possibly off-topic answer."}
    yield "done", {"msg_id": "m", "query_type": "FACTUAL", "low_confidence": True, "top_retrieval_score": 0.18}


def test_low_confidence_caution_renders(monkeypatch):
    """A low-confidence answer shows the 'may be outside the FastAPI docs' caution."""
    import api_client

    monkeypatch.setattr(api_client, "stream_query", _streamed_lowconf)
    monkeypatch.setattr(api_client, "send_feedback", lambda *a, **k: True)
    at = AppTest.from_file(_APP, default_timeout=30)
    at.run()
    at.chat_input[0].set_value("what is the airspeed velocity of a swallow?").run()
    assert at.session_state["messages"][1]["metadata"]["low_confidence"] is True
    assert any("Low retrieval confidence" in str(m.value) for m in at.markdown)


def test_toggles_in_session_state(at):
    at.run()
    assert at.session_state["use_cache"] is True
    assert at.session_state["use_streaming"] is True


def test_new_chat_resets(at):
    at.run()
    at.chat_input[0].set_value("first question").run()
    assert len(at.session_state["messages"]) == 2
    # New Chat button is the first button in the sidebar.
    next(b for b in at.button if "New Chat" in b.label).click().run()
    assert at.session_state["messages"] == []


def _agent_stream(task, session_id=None):
    yield "session", {"session_id": "s"}
    yield "agent_step", {"name": "plan", "status": "running"}
    yield "agent_step", {"name": "plan", "status": "done", "detail": "3 concepts"}
    yield "agent_step", {"name": "retrieve", "status": "running"}
    yield "context", {"rank": 1, "content": "ctx", "metadata": {"file_path": "docs/x.md"}}
    yield "agent_step", {"name": "retrieve", "status": "done", "detail": "1 sources"}
    yield "agent_step", {"name": "write", "status": "running", "detail": "attempt 1"}
    yield "code", {"attempt": 1, "content": "from fastapi import FastAPI"}
    yield "agent_step", {"name": "write", "status": "done", "detail": "attempt 1"}
    yield "agent_step", {"name": "run", "status": "running", "detail": "attempt 1"}
    yield "exec_result", {"attempt": 1, "exit_code": 0, "stdout": "status 200", "stderr": "", "duration_ms": 80}
    yield "agent_step", {"name": "run", "status": "done", "detail": "exit 0"}
    yield "token", {"token": "It validates input and returns 422 [1]."}
    yield "done", {"success": True, "attempts": 1, "msg_id": "msg_a", "session_id": "s"}


def test_agent_mode_runs_and_stores_run(monkeypatch):
    import api_client

    monkeypatch.setattr(api_client, "stream_agent", _agent_stream)
    at = AppTest.from_file(_APP, default_timeout=30)
    at.session_state["mode"] = "▶ Agent"
    at.session_state["agent_pending"] = "Write and run an endpoint"
    at.run()
    assert not at.exception
    run = at.session_state["agent_run"]
    assert run["final"]["success"] is True
    assert run["code_attempts"][1].startswith("from fastapi")
    assert "validates input" in run["answer"]


def test_playground_fallback_editor_runs(monkeypatch):
    import api_client
    import playground_view

    monkeypatch.setattr(playground_view, "_HAS_MONACO", False)  # force the text_area fallback (AC3.8)
    monkeypatch.setattr(
        api_client,
        "execute_code",
        lambda code, session_id="", **k: {
            "ok": True,
            "exit_code": 0,
            "stdout": "status 200",
            "stderr": "",
            "duration_ms": 40,
        },
    )
    at = AppTest.from_file(_APP, default_timeout=30)
    at.session_state["mode"] = "⌨ Playground"
    at.session_state["playground_code"] = "print('hi')"
    at.run()
    assert not at.exception
    next(b for b in at.button if b.label == "▶ Run").click().run()
    assert at.session_state["pg_result"]["stdout"] == "status 200"


def test_agent_teaser_chip_switches_mode_without_crash(monkeypatch):
    """Regression: clicking a mode-switch chip must not write the widget-bound `mode`
    key after the radio is built (the StreamlitAPIException the visual suite caught)."""
    import api_client

    monkeypatch.setattr(api_client, "stream_agent", _agent_stream)
    at = AppTest.from_file(_APP, default_timeout=30)
    at.run()
    next(b for b in at.button if "Write & run" in b.label).click().run()
    assert not at.exception  # the bug raised here
    assert at.session_state["mode"] == "▶ Agent"
    assert at.session_state["agent_run"]["final"]["success"] is True


def test_non_streaming_toggle_uses_send_query(monkeypatch):
    """use_streaming=False must route through /query (send_query), same render (AC2.2)."""
    import api_client

    called = {}

    def fake_send_query(query, session_id=None, use_cache=True, **_k):
        called["query"] = query
        return {
            "answer": "Use Depends() for dependency injection [1].",
            "contexts": [{"rank": 1, "content": "x", "metadata": {"file_path": "a.md"}}],
            "metadata": {"cache_hit": False, "query_type": "FACTUAL"},
            "session_id": "s",
            "msg_id": "m",
        }

    monkeypatch.setattr(api_client, "send_query", fake_send_query)
    at = AppTest.from_file(_APP, default_timeout=30)
    at.session_state["use_streaming"] = False
    at.run()
    at.chat_input[0].set_value("What does Depends do?").run()
    assert called["query"] == "What does Depends do?"
    assert "Depends" in at.session_state["messages"][1]["content"]


def test_playground_guard_warning_renders(monkeypatch):
    import api_client
    import playground_view

    monkeypatch.setattr(playground_view, "_HAS_MONACO", False)
    monkeypatch.setattr(
        api_client,
        "execute_code",
        lambda *a, **k: {"guard": "oversize", "stderr": "That's a lot of code — the sandbox takes up to 10 KB."},
    )
    at = AppTest.from_file(_APP, default_timeout=30)
    at.session_state["mode"] = "⌨ Playground"
    at.session_state["playground_code"] = "x" * 50
    at.run()
    next(b for b in at.button if b.label == "▶ Run").click().run()
    assert any("10 KB" in str(w.value) for w in at.warning)


def test_playground_fix_with_ai_shows_preview(monkeypatch):
    import api_client
    import playground_view

    monkeypatch.setattr(playground_view, "_HAS_MONACO", False)
    monkeypatch.setattr(
        api_client,
        "execute_code",
        lambda *a, **k: {"ok": False, "exit_code": 1, "stdout": "", "stderr": "SyntaxError", "duration_ms": 8},
    )
    monkeypatch.setattr(api_client, "fix_code", lambda *a, **k: {"fixed_code": "fixed = True", "guard": None})
    at = AppTest.from_file(_APP, default_timeout=30)
    at.session_state["mode"] = "⌨ Playground"
    at.session_state["playground_code"] = "broken("
    at.run()
    next(b for b in at.button if b.label == "▶ Run").click().run()
    next(b for b in at.button if "Fix with AI" in b.label).click().run()
    assert at.session_state["pg_fix_preview"] == "fixed = True"
