"""Agent mode UI (Phase 3) — watch FastPilot build, run, and self-correct code.

Streams ``/agent/stream`` events into a live step timeline + terminal + explanation,
then stores the completed run in session state and renders it statically (so failed
attempts collapse, the final code carries a Send-to-Playground handoff, and feedback
widgets get stable keys).
"""

from __future__ import annotations

import api_client
import feature_flags
import requests
import streamlit as st
import styles

SAMPLE_TASK = "Write and run an endpoint that validates a user payload with Pydantic and returns 422 on bad input."


# The first-pass roadmap, pre-rendered dimmed so the user sees what's coming. Fix/run
# retries beyond the first pass are appended live as their events arrive.
_ROADMAP = ("plan", "retrieve", "write", "run")


def _seed_steps() -> list[dict]:
    return [{"name": n, "status": "pending", "detail": ""} for n in _ROADMAP]


def _upsert_step(steps: list[dict], data: dict) -> None:
    name, status = data.get("name"), data.get("status")
    if status == "running":
        for step in steps:  # activate the first pending step of this name (the roadmap)
            if step["name"] == name and step["status"] == "pending":
                step["status"] = "running"
                step["detail"] = data.get("detail", "")
                return
        steps.append({"name": name, "status": "running", "detail": data.get("detail", "")})
        return
    for step in reversed(steps):
        if step["name"] == name and step["status"] == "running":
            step["status"] = status
            step["detail"] = data.get("detail", step["detail"])
            return
    steps.append({"name": name, "status": status, "detail": data.get("detail", "")})


def _render_run(run: dict) -> None:
    st.markdown(styles.timeline_html(run["steps"]), unsafe_allow_html=True)

    attempts = run["code_attempts"]
    success = run.get("final", {}).get("success")
    for attempt in sorted(attempts):
        is_last = attempt == max(attempts)
        # The last attempt is always shown expanded — the working code on success, or the
        # last thing tried on an honest failure (mock screen 05). Earlier attempts collapse.
        if is_last:
            badge = "" if success else " ✗"
            st.markdown(f"**Code · attempt {attempt}{badge}**")
            st.code(attempts[attempt], language="python")
        else:
            with st.expander(f"Code · attempt {attempt} ✗", expanded=False):
                st.code(attempts[attempt], language="python")

    last_exec = run["exec_results"].get(max(run["exec_results"])) if run["exec_results"] else None
    if last_exec:
        st.markdown(
            styles.terminal_html(
                last_exec.get("stdout", ""),
                last_exec.get("stderr", ""),
                last_exec.get("exit_code", -1),
                last_exec.get("duration_ms", 0),
            ),
            unsafe_allow_html=True,
        )

    if run.get("answer"):
        st.markdown(styles.render_answer(run["answer"]), unsafe_allow_html=True)

    if run.get("contexts"):
        with st.expander(f"Sources ({len(run['contexts'])})"):
            for ctx in run["contexts"]:
                meta = ctx.get("metadata", {})
                title = meta.get("title") or styles.source_label(meta)
                url = meta.get("url")
                label = f'<a href="{url}" target="_blank" class="fp-src-link">{title}</a>' if url else title
                rank = ctx.get("rank", "?")
                st.markdown(f'<span class="fp-src-path">[{rank}] {label}</span>', unsafe_allow_html=True)

    if attempts and feature_flags.playground_enabled() and st.button("⌨ Send to Playground", key="send_to_pg"):
        st.session_state.playground_code = attempts[max(attempts)]
        st.session_state.pending_mode = "⌨ Playground"  # applied before the mode radio (app.main)
        st.rerun()


def _stream_run(task: str) -> None:
    steps: list[dict] = _seed_steps()
    code_attempts: dict[int, str] = {}
    exec_results: dict[int, dict] = {}
    contexts: list[dict] = []
    answer = ""
    final: dict = {}

    timeline_ph = st.empty()
    term_ph = st.empty()
    answer_ph = st.empty()
    timeline_ph.markdown(styles.timeline_html(steps), unsafe_allow_html=True)  # show the roadmap immediately
    try:
        for event, data in api_client.stream_agent(task, st.session_state.session_id):
            if event == "session":
                st.session_state.session_id = data.get("session_id", st.session_state.session_id)
            elif event == "agent_step":
                _upsert_step(steps, data)
                timeline_ph.markdown(styles.timeline_html(steps), unsafe_allow_html=True)
            elif event == "context":
                contexts.append(data)
            elif event == "code":
                code_attempts[data["attempt"]] = data["content"]
            elif event == "exec_result":
                exec_results[data["attempt"]] = data
                term_ph.markdown(
                    styles.terminal_html(
                        data.get("stdout", ""),
                        data.get("stderr", ""),
                        data.get("exit_code", -1),
                        data.get("duration_ms", 0),
                    ),
                    unsafe_allow_html=True,
                )
            elif event == "token":
                answer += data.get("token", "")
                answer_ph.markdown(styles.render_answer(answer) + " ▌", unsafe_allow_html=True)
            elif event == "error":
                answer_ph.error(data.get("error", "Agent run failed."))
            elif event == "done":
                final = data
    except requests.RequestException:
        answer_ph.error(
            "FastPilot's backend isn't reachable right now. Your conversation is safe. "
            "Check that the API server is running, then try again."
        )
        return

    st.session_state.agent_run = {
        "task": task,
        "steps": steps,
        "code_attempts": code_attempts,
        "exec_results": exec_results,
        "contexts": contexts,
        "answer": answer,
        "final": final,
    }
    st.rerun()


def render() -> None:
    st.markdown(
        '<div class="fp-hero"><div class="fp-wordmark">⚡ FastPilot · Agent</div></div>', unsafe_allow_html=True
    )
    if st.session_state.get("agent_run"):
        st.markdown(f"**Task:** {st.session_state.agent_run['task']}")
        _render_run(st.session_state.agent_run)

    task = st.session_state.pop("agent_pending", None) or st.chat_input("Describe an endpoint to build & run…")
    if task:
        st.session_state.agent_run = None
        st.markdown(f"**Task:** {task}")
        _stream_run(task)

    st.markdown(
        '<div class="fp-disclaimer">Code runs in an isolated sandbox — 15s limit, no network.</div>',
        unsafe_allow_html=True,
    )
