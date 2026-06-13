# Augmentation Decisions (Week 6) — BONUS

> Components live in `app/augmentations/` (`agent_orchestrator.py`, `code_executor.py`,
> `rate_limit.py`, `security.py`). All numbers below are measured live through the
> production pipeline; evidence JSON is in `evaluations/eval_results/` (filenames cited inline).

## Gap identified
The RAG system answers *how* to do something — but for the `CODE_GENERATION` slice, a
correct-sounding answer is not the same as **working code**. Retrieval + generation gave
the user a snippet they still had to copy out, run, and debug themselves; nothing verified
that the generated FastAPI code actually executes or behaves as claimed. The honest Week-4
finding ("T1b wins answers, judges can't see exact-file retrieval") underlined that *answer
quality ≠ runnable correctness*. That last mile — **write it, run it, prove it** — was unclosed.

## Augmentation selected
A **grounded code-runner agent** (no class equivalent), plus a user-facing **Playground**
(D11) that reuses the same sandbox:

- **Deterministic orchestrator** (`agent_orchestrator.py`) — a code-driven loop mirroring the
  class CRAG routing philosophy, *not* free-form LLM tool-calling: InputGuard → plan →
  retrieve (T1b) → write (grounded, cites `[n]`) → AST-scan + sandbox run → self-correct
  (≤2 fix attempts, each fix prompt carrying the previous traceback) → explain, or an honest
  failure. Chosen over Haystack `Agent`+`Tool` for **demo determinism and unit-testability**;
  every step streams as an SSE event.
- **Self-verification (D7)** — generated code exercises itself in-process with
  `fastapi.testclient.TestClient` and its own `assert`s, so "running" never binds a port and
  the output is a clean request/response log.
- **Sandbox (D6, `code_executor.py`)** — AST denylist → `python -I` subprocess isolation
  (scrubbed env, temp-dir cwd, own process group) → `RLIMIT` CPU/AS/FSIZE → wall-timeout
  killpg → socket-guard prelude. The same scan+sandbox path backs the Playground `/execute`.
- **Playground (D11)** — Monaco editor (with `st.text_area` fallback) → `/execute`; "Fix with
  AI" → `/fix` reuses `AGENT_FIX_PROMPT`. Caps: 10 KB, 15 s wall, 3 runs/min/session,
  `PLAYGROUND_ENABLED` kill switch. The one non-class dependency, contained to one view + one
  endpoint.

## Measurement (Phase 4, live through the real pipeline)
**Success & self-correction** (`agent_eval.json`, 10 golden tasks, `06_run_agent_eval.py`):

| Metric | Result |
|---|---|
| Success **with** self-correction | **10/10 (100%)** — clears AC3.1 (≥8/10) and the 0.80 gate |
| Success **first attempt only** | 40–50% (LLM-variable across runs) |
| **Self-correction gain** | **+50 to +60 points** — *this delta is the augmentation's value* |
| Self-correcting tasks | 5–6/10 fail attempt 1 and recover; `response_model` needed **two** fix rounds |

The loop is doing real work, not cosmetics: roughly half of all tasks only pass *because* the
agent reads its own traceback and fixes the code.

**Grounding** (`agent_quality.json`, `08_agent_quality_checks.py`): after making citation
mandatory in the code/fix prompts, **6/6 sampled tasks cite `[n]`**, and **25/27 cited chunks
(93%) actually mention the API used** — clears AC3.4 (≥80%).

**Fix-with-AI** (`agent_quality.json`): **3/3** seeded broken snippets (syntax error, missing
import, failing assertion) come back clean after a single fix round — clears AC3.9 (≥2/3).

**Human-in-the-loop check** (`human_verification.json` + `agent_code/`,
`09_human_verification_probes.py`): 10 hand-written edge probes the agent's own asserts never
covered, run through the Playground sandbox — **10/10 held**. The honest read: most wins are
FastAPI/Pydantic framework guarantees surfacing through thin self-tests (the strongest real-logic
signal is `response_model` stripping both `password` *and* a client-injected `is_admin` it never
tested). **One real limitation surfaced**: the `depends` solution sets no lower bound, so
`skip=-5` returns `200 {skip:-5,limit:10}` — not a task failure, but a robustness gap the agent's
self-verification could never catch. That is exactly why the human step exists.

## Honest limits
- **Single-file apps only** — no database, no external network, no multi-module projects.
- **Sandbox is single-box, defense-in-depth — not a hard boundary.** The AST scan blocks the
  textbook reflection escape (`().__class__.__bases__[0].__subclasses__()`), the reflection builtins
  (`getattr`/`globals`/`vars`/…) it would lean on, and direct `open` filesystem access — so the
  copy-paste escapes a curious user would actually try are closed. But a *pure in-process Python*
  sandbox can never be a true guarantee (a sufficiently obscure technique may exist); only OS-level
  isolation is. The remaining layers cap the blast radius (scrubbed env = **no secrets to steal**,
  socket guard = no network, rlimits + wall-timeout, `PLAYGROUND_ENABLED` kill switch). The documented
  production-grade path is a **Docker backend** (`--network none --memory 256m`) — the only hard
  boundary, deferred because Railway offers no docker-in-docker.
- **Self-verification only tests what the agent thought to test** — see the `depends` finding;
  robust endpoints often lean on the framework's contracts rather than the agent's thoroughness.
- **No keystroke autocomplete** in the Playground — Streamlit's rerun model + the Monaco iframe
  boundary can't deliver acceptable latency; the natural next improvement, listed honestly.
