"""FastPilot frontend (Streamlit) — Phase 2.

Chat mode is live: welcome state with suggestion chips, SSE streaming with status
badges + inline citations, a sources expander, and thumbs feedback. Agent and
Playground are shown in the learning-loop mode switcher but land in Phase 3.

Streamlit reruns top-to-bottom on every interaction; live streaming uses the class
pattern (an ``st.empty()`` placeholder updated per token), then the turn is appended
to ``st.session_state.messages`` and rendered from history on the next run.
"""

from __future__ import annotations

import uuid

import agent_view
import api_client
import playground_view
import requests
import streamlit as st
import styles

MODES = ["💬 Chat", "▶ Agent", "⌨ Playground"]
_MODE_LABEL = {
    "💬 Chat": "💬 Chat — understand",
    "▶ Agent": "▶ Agent — watch",
    "⌨ Playground": "⌨ Playground — practice",
}

SUGGESTIONS = [
    ("Path & query params", "How do I declare a path parameter and a query parameter with types?"),
    ("Add JWT auth", "How do I add JWT authentication to a FastAPI app?"),
    ("Validate with Pydantic", "How do I validate a request body with a Pydantic model and return 422 on bad input?"),
    ("▶ Write & run a sample endpoint", None),  # agent teaser → switches mode
]


def _active_theme() -> str:
    """The viewer's current Streamlit/OS theme ("light"/"dark"), defaulting the toggle so
    first paint matches their system. Read-only; the sidebar toggle can override it."""
    try:
        t = st.context.theme.type
        return t if t in ("light", "dark") else "dark"
    except Exception:  # noqa: BLE001 - st.context may be absent (e.g. AppTest)
        return "dark"


def _init_state() -> None:
    ss = st.session_state
    ss.setdefault("messages", [])
    ss.setdefault("session_id", f"sess_{uuid.uuid4().hex}")
    ss.setdefault("use_cache", True)
    ss.setdefault("use_streaming", True)
    ss.setdefault("mode", MODES[0])
    ss.setdefault("pending", None)
    ss.setdefault("handled_fb", set())
    ss.setdefault("theme", _active_theme())


def _new_chat() -> None:
    st.session_state.messages = []
    st.session_state.session_id = f"sess_{uuid.uuid4().hex}"
    st.session_state.handled_fb = set()
    st.session_state.pending = None


def _sidebar() -> None:
    with st.sidebar:
        st.markdown("### ⚡ FastPilot")
        st.button("＋ New Chat", use_container_width=True, on_click=_new_chat)
        st.divider()
        st.radio(
            "Mode",
            MODES,
            key="mode",
            format_func=lambda m: _MODE_LABEL[m],
        )
        st.markdown('<div class="fp-mode-note">Understand → watch → practice</div>', unsafe_allow_html=True)
        st.divider()
        st.toggle(
            "Semantic Cache",
            key="use_cache",
            help="Repeated questions answer instantly from a semantic cache. Turn off to always generate fresh.",
        )
        st.toggle(
            "Stream Responses",
            key="use_streaming",
            help="Show answers word by word as they generate.",
        )
        st.divider()
        st.segmented_control(
            "Theme",
            ["light", "dark"],
            key="theme",
            format_func=lambda t: "☀️ Light" if t == "light" else "🌙 Dark",
            help="Switch the whole app between light and dark.",
        )
        st.caption(f"Session: {st.session_state.session_id[:14]}…")


# --- Rendering ------------------------------------------------------------
def _render_sources(contexts: list[dict]) -> None:
    if not contexts:
        return
    with st.expander(f"Sources ({len(contexts)})"):
        for ctx in contexts:
            meta = ctx.get("metadata", {})
            title = meta.get("title") or styles.source_label(meta)
            url = meta.get("url")
            label = f'<a href="{url}" target="_blank" class="fp-src-link">{title}</a>' if url else title
            ctype = meta.get("category", meta.get("file_type", "source"))
            score = ctx.get("score")
            score_txt = f" · {score:.2f}" if isinstance(score, (int, float)) else ""
            st.markdown(
                f'<span class="fp-src-path">[{ctx.get("rank", "?")}] {label}</span> '
                f'<span class="fp-src-type">{ctype}</span>{score_txt}',
                unsafe_allow_html=True,
            )
            snippet = (ctx.get("content") or "")[:200].replace("\n", " ")
            st.markdown(f'<div class="fp-src-snippet">{snippet}…</div>', unsafe_allow_html=True)


@st.dialog("Help us improve")
def _feedback_dialog(idx: int, msg: dict) -> None:
    reason = st.radio(
        "What went wrong with this answer?",
        ["Incorrect", "Not relevant", "Incomplete", "Too verbose", "Other"],
        key=f"reason_{idx}",
    )
    comment = st.text_area("Optional — tell us more", key=f"comment_{idx}")
    cancel, submit = st.columns(2)
    if cancel.button("Cancel", use_container_width=True, key=f"cancel_{idx}"):
        st.rerun()
    if submit.button("Submit", type="primary", use_container_width=True, key=f"submit_{idx}"):
        meta = msg.get("metadata", {})
        api_client.send_feedback(
            st.session_state.session_id,
            msg.get("msg_id", ""),
            "down",
            comment=comment,
            reason=reason,
            trace_id=meta.get("trace_id", "") or "",
        )
        st.rerun()


def _render_feedback(idx: int, msg: dict) -> None:
    fb = st.feedback("thumbs", key=f"fb_{idx}")
    if fb is None or idx in st.session_state.handled_fb:
        return
    st.session_state.handled_fb.add(idx)
    meta = msg.get("metadata", {})
    if fb == 1:
        api_client.send_feedback(
            st.session_state.session_id, msg.get("msg_id", ""), "up", trace_id=meta.get("trace_id", "") or ""
        )
    else:
        _feedback_dialog(idx, msg)


def _render_assistant(msg: dict, idx: int) -> None:
    meta = msg.get("metadata", {})
    badges = styles.badges_html(
        rewritten=bool(meta.get("rewritten")),
        cache_hit=bool(meta.get("cache_hit")),
        query_type=meta.get("query_type"),
        guarded=bool(meta.get("refused")),
    )
    if badges:
        st.markdown(badges, unsafe_allow_html=True)
    note = styles.rewrite_note_html(meta.get("standalone_query"))
    if note:
        st.markdown(note, unsafe_allow_html=True)
    if meta.get("low_confidence"):
        st.markdown(styles.low_confidence_note_html(), unsafe_allow_html=True)
    st.markdown(styles.render_answer(msg["content"]), unsafe_allow_html=True)
    _render_sources(msg.get("contexts", []))
    cap = []
    if isinstance(meta.get("latency_ms"), (int, float)):
        cap.append(f"{meta['latency_ms'] / 1000:.1f}s")
    if isinstance(meta.get("cost_usd"), (int, float)) and meta["cost_usd"] > 0:
        cap.append(f"${meta['cost_usd']:.4f}")
    if msg.get("contexts"):
        cap.append(f"{len(msg['contexts'])} sources")
    if cap:
        st.caption(" · ".join(cap))
    _render_feedback(idx, msg)


def _render_history() -> None:
    for idx, msg in enumerate(st.session_state.messages):
        with st.chat_message(msg["role"]):
            if msg["role"] == "assistant":
                _render_assistant(msg, idx)
            else:
                st.markdown(msg["content"])


# --- Streaming ------------------------------------------------------------
def _stream_answer(prompt: str) -> dict:
    """Stream the assistant answer into placeholders; return the message dict."""
    badge_ph = st.empty()
    note_ph = st.empty()
    lowconf_ph = st.empty()
    answer_ph = st.empty()
    buffer, contexts, meta = "", [], {}
    rewritten = cache_hit = False
    qtype = None
    try:
        stream = (
            api_client.stream_query(prompt, st.session_state.session_id, st.session_state.use_cache)
            if st.session_state.use_streaming
            else _fake_stream_from_post(prompt)
        )
        for event, data in stream:
            if event == "session":
                st.session_state.session_id = data.get("session_id", st.session_state.session_id)
            elif event == "rewrite":
                rewritten = True
                note_ph.markdown(styles.rewrite_note_html(data.get("standalone")), unsafe_allow_html=True)
            elif event == "cache_status":
                cache_hit = bool(data.get("cache_hit"))
            elif event == "classification":
                qtype = data.get("category")
            elif event == "context":
                contexts.append(data)
            elif event == "token":
                buffer += data.get("token", "")
                badge_ph.markdown(
                    styles.badges_html(rewritten=rewritten, cache_hit=cache_hit, query_type=qtype),
                    unsafe_allow_html=True,
                )
                answer_ph.markdown(styles.render_answer(buffer) + " ▌", unsafe_allow_html=True)
            elif event == "error":
                answer_ph.error(data.get("error", "Something went wrong."))
            elif event == "done":
                meta = data
    except requests.RequestException:
        answer_ph.error(
            "FastPilot's backend isn't reachable right now. Your conversation is safe. "
            "Check that the API server is running, then try again."
        )
        buffer = buffer or "_(backend unavailable)_"

    answer_ph.markdown(styles.render_answer(buffer), unsafe_allow_html=True)
    if meta.get("low_confidence"):
        lowconf_ph.markdown(styles.low_confidence_note_html(), unsafe_allow_html=True)
    _render_sources(contexts)
    return {
        "role": "assistant",
        "content": buffer,
        "contexts": contexts,
        "msg_id": meta.get("msg_id", ""),
        "metadata": {
            **meta,
            "rewritten": rewritten,
            "cache_hit": cache_hit,
            "query_type": qtype or meta.get("query_type"),
        },
    }


def _fake_stream_from_post(prompt: str):
    """Non-streaming path: call /query and replay it as a single token + done so the
    render code stays identical (AC2.2 — visually one path)."""
    body = api_client.send_query(prompt, st.session_state.session_id, st.session_state.use_cache)
    meta = body.get("metadata", {})
    yield "session", {"session_id": body.get("session_id", st.session_state.session_id)}
    if meta.get("is_follow_up"):
        yield "rewrite", {"standalone": meta.get("standalone_query")}
    yield "cache_status", {"cache_hit": meta.get("cache_hit", False)}
    if meta.get("query_type"):
        yield "classification", {"category": meta["query_type"]}
    for ctx in body.get("contexts", []):
        yield "context", ctx
    yield "token", {"token": body.get("answer", "")}
    yield "done", {**meta, "msg_id": body.get("msg_id", "")}


def _handle_prompt(prompt: str) -> None:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        assistant = _stream_answer(prompt)
    st.session_state.messages.append(assistant)
    st.rerun()


# --- Welcome --------------------------------------------------------------
def _welcome() -> None:
    st.markdown(
        '<div class="fp-hero">'
        '<div class="fp-wordmark">⚡ FastPilot</div>'
        "<h1>Learn FastAPI by building.</h1>"
        "<p>Ask anything, watch the agent build and run working examples, then tweak the code yourself — "
        "every answer grounded in the official docs, the full-stack template, and real GitHub issues.</p></div>",
        unsafe_allow_html=True,
    )
    cols = st.columns(2)
    for i, (label, query) in enumerate(SUGGESTIONS):
        with cols[i % 2]:
            if st.button(label, key=f"chip_{i}", use_container_width=True):
                if query is None:  # agent teaser → Agent mode, pre-filled
                    st.session_state.pending_mode = MODES[1]
                    st.session_state.agent_pending = agent_view.SAMPLE_TASK
                else:
                    st.session_state.pending = query
                st.rerun()


# --- Main -----------------------------------------------------------------
def main() -> None:
    st.set_page_config(page_title="FastPilot", page_icon="⚡", layout="centered", initial_sidebar_state="expanded")
    _init_state()
    styles.inject_css(st, st.session_state.theme)
    # Apply a requested mode switch BEFORE the sidebar radio (key="mode") is built —
    # Streamlit forbids writing a widget-bound key after the widget is instantiated.
    if st.session_state.get("pending_mode"):
        st.session_state.mode = st.session_state.pop("pending_mode")
    _sidebar()

    if st.session_state.mode == MODES[1]:
        agent_view.render()
        return
    if st.session_state.mode == MODES[2]:
        playground_view.render()
        return

    if not st.session_state.messages and not st.session_state.pending:
        _welcome()

    _render_history()

    placeholder = "Ask a follow-up…" if st.session_state.messages else "Ask about FastAPI…"
    prompt = st.session_state.pending or st.chat_input(placeholder)
    st.session_state.pending = None
    if prompt:
        _handle_prompt(prompt)

    st.markdown(
        '<div class="fp-disclaimer">Answers are AI-generated from the FastAPI corpus and may contain errors.</div>',
        unsafe_allow_html=True,
    )


main()
