"""Playground mode UI (Phase 3, D11) — edit and run FastAPI code in the same sandbox.

Monaco editor via ``streamlit-monaco`` with an automatic ``st.text_area`` fallback
(AC3.8 — the feature survives the component breaking). Run → ``/execute``; failures
offer Fix-with-AI (``/fix``) and a hand-off to Chat. Guard responses (oversize, rate
limit, denylist, disabled) render as friendly warnings, never raw errors.
"""

from __future__ import annotations

import api_client
import requests
import streamlit as st
import styles

try:
    from streamlit_monaco import st_monaco

    _HAS_MONACO = True
except Exception:  # noqa: BLE001 - any import failure → text_area fallback
    _HAS_MONACO = False

PRESETS = {
    "Hello endpoint": (
        "from fastapi import FastAPI\n"
        "from fastapi.testclient import TestClient\n\n"
        "app = FastAPI()\n\n"
        "@app.get('/')\n"
        "def root():\n"
        "    return {'message': 'hello'}\n\n"
        "client = TestClient(app)\n"
        "r = client.get('/')\n"
        "print(r.status_code, r.json())\n"
        "assert r.status_code == 200\n"
    ),
    "Pydantic validation": (
        "from fastapi import FastAPI\n"
        "from fastapi.testclient import TestClient\n"
        "from pydantic import BaseModel, Field\n\n"
        "class User(BaseModel):\n"
        "    name: str\n"
        "    age: int = Field(gt=0)\n\n"
        "app = FastAPI()\n\n"
        "@app.post('/users')\n"
        "def create(user: User):\n"
        "    return user\n\n"
        "client = TestClient(app)\n"
        "print('valid:', client.post('/users', json={'name': 'Ada', 'age': 36}).status_code)\n"
        "print('invalid:', client.post('/users', json={'name': 'Ada', 'age': -1}).status_code)\n"
        "assert client.post('/users', json={'name': 'Ada', 'age': -1}).status_code == 422\n"
    ),
    "Depends example": (
        "from fastapi import FastAPI, Depends\n"
        "from fastapi.testclient import TestClient\n\n"
        "def pagination(skip: int = 0, limit: int = 10):\n"
        "    return {'skip': skip, 'limit': limit}\n\n"
        "app = FastAPI()\n\n"
        "@app.get('/items')\n"
        "def items(p: dict = Depends(pagination)):\n"
        "    return p\n\n"
        "client = TestClient(app)\n"
        "r = client.get('/items?skip=5')\n"
        "print(r.status_code, r.json())\n"
        "assert r.json()['skip'] == 5\n"
    ),
}


def _editor(value: str) -> str:
    if _HAS_MONACO:
        try:
            return st_monaco(value=value, height="340px", language="python", theme="streamlit") or value
        except Exception:  # noqa: BLE001 - render failure → fallback editor, feature intact
            pass
    code = st.text_area("Code", value=value, height=340, key="pg_textarea", label_visibility="collapsed")
    st.caption("Plain editor (the Monaco component is unavailable here).")
    return code


def _render_guard(result: dict) -> None:
    guard = result.get("guard")
    if guard == "disabled":
        st.warning("The Playground is turned off on the server right now.")
    else:
        st.warning(result.get("stderr", "That run hit a sandbox limit."))


def render() -> None:
    st.markdown(
        '<div class="fp-hero"><div class="fp-wordmark">⚡ FastPilot · Playground</div></div>', unsafe_allow_html=True
    )

    default = st.session_state.get("playground_code") or next(iter(PRESETS.values()))
    preset = st.selectbox("Start from", ["— current —", *PRESETS.keys()], index=0)
    if preset != "— current —":
        default = PRESETS[preset]
        st.session_state.playground_code = default

    code = _editor(default)
    run = st.button("▶ Run", type="primary")

    if run:
        st.session_state.playground_code = code
        st.session_state.pg_fix_preview = None
        try:
            st.session_state.pg_result = api_client.execute_code(code, st.session_state.session_id)
        except requests.RequestException:
            st.session_state.pg_result = {"guard": "backend", "stderr": "Backend unreachable — is the API running?"}

    result = st.session_state.get("pg_result")
    if result:
        if result.get("guard"):
            _render_guard(result)
        else:
            st.markdown(
                styles.terminal_html(
                    result.get("stdout", ""),
                    result.get("stderr", ""),
                    result.get("exit_code", -1),
                    result.get("duration_ms", 0),
                ),
                unsafe_allow_html=True,
            )
            if result.get("exit_code", 0) != 0:
                cols = st.columns(2)
                if cols[0].button("✨ Fix with AI"):
                    try:
                        fix = api_client.fix_code(code, result.get("stderr", ""), st.session_state.session_id)
                        st.session_state.pg_fix_preview = fix.get("fixed_code")
                    except requests.RequestException:
                        st.warning("Couldn't reach the fixer — is the backend running?")
                    st.rerun()
                if cols[1].button("Ask FastPilot about this error"):
                    st.session_state.pending_mode = "💬 Chat"
                    st.session_state.pending = (
                        "I got this error running FastAPI code:\n\n"
                        f"{result.get('stderr', '')[:500]}\n\nWhat's going wrong and how do I fix it?"
                    )
                    st.rerun()

    preview = st.session_state.get("pg_fix_preview")
    if preview:
        st.markdown("**Suggested fix** — a preview; your editor is untouched until you apply.")
        diff = styles.diff_html(st.session_state.get("playground_code", ""), preview)
        if diff:
            st.markdown(diff, unsafe_allow_html=True)
        with st.expander("Full fixed code", expanded=not diff):
            st.code(preview, language="python")
        a, d = st.columns(2)
        if a.button("Apply", type="primary"):
            st.session_state.playground_code = preview
            st.session_state.pg_fix_preview = None
            st.session_state.pg_result = None
            st.rerun()
        if d.button("Dismiss"):
            st.session_state.pg_fix_preview = None
            st.rerun()

    st.markdown(
        '<div class="fp-disclaimer">Code runs in an isolated sandbox — 15s limit, no network.</div>',
        unsafe_allow_html=True,
    )
