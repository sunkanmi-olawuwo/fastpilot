# Production Decisions (Week 5)

> **Status:** scaffold (Phase 0). Written in Phase 5. One entry per service: added/skipped, why, evidence.

Every production service below is an explicit **add** or **skip** with a reason and evidence — not
a template default. Components live in `app/services/` and `app/augmentations/`.

### SSE streaming — **added**
**Why:** answers run 1.7k–10k chars; streaming token-by-token makes the wait legible instead of a
30-second blank. **How:** `text/event-stream` with the class week-5 event protocol
(`session / rewrite / cache_status / classification / context / token / done / error`), consumed in
Streamlit via `requests.post(..., stream=True)` + `iter_lines()`. **Hardening:** a mid-stream
disconnect cancels the producer task; once tokens have emitted we surface the error rather than retry
(no garbled double-answer). **Evidence:** SSE event-order + post-emit-failure tests in
`tests/test_pipeline.py` / `test_api.py`.

### Semantic cache — **added, threshold calibrated**
**Why:** repeated/paraphrased questions are common for a learning tool; a cache answers them instantly
at ~$0. **How:** Redis HNSW/KNN over voyage-4-lite query embeddings (`FT.CREATE`/`FT.SEARCH`); a miss
embeds the query **once** and reuses that vector for retrieval + cache-set (verified byte-identical,
cosine 1.000000) — saving 2 Voyage calls per miss. **Calibration (AC4.2):** the paraphrase/near-miss
distance bands *overlap* (a true paraphrase at 0.31 sits beyond the closest near-miss at 0.23), so the
strict "100% paraphrase / 0 near-miss" target is unachievable with this embedder. We chose **safety**
(zero wrong-answer serving) and set the threshold to **0.16** (4/6 paraphrases hit, 0/6 near-misses,
0.068 margin) — 4× the hit-rate of the original 0.06 with no wrong-answer risk. **Evidence:**
`evaluations/eval_results/cache_threshold.json`; a live paraphrase hit observed during the soak.

### Conversation memory + conditional rewrite — **added**
**Why:** follow-ups ("can it be an integer?") are meaningless without history. **How:** Redis-backed
windowed memory per `session_id` (TTL 24h); a follow-up turn is rewritten to a standalone query before
retrieval, a first turn is not (no phantom rewrite). **Honest detail:** refusals don't pollute memory —
a refused first turn stays a true first turn. **Evidence:** the dogfood log shows live rewrites
resolving referents ("can it be an integer?" → "Can a query parameter with a default value be an
integer?").

### Query router — **added**
**Why:** a FACTUAL question and a CODE_GENERATION request deserve different prompts/temperature. **How:**
a lightweight classifier tags each query (FACTUAL / HOW_TO / TROUBLESHOOTING / CODE_GENERATION) and
selects the matching versioned prompt; defaults safely to FACTUAL on a parse failure. **Evidence:**
router parse-edge tests; classification spans visible in Opik.

### Redis graceful degradation — **design choice**
**Why:** a downed Redis must not 5xx a learning session. **How:** missing creds or a *runtime* Redis
failure demote the cache and conversation memory to in-memory/no-op symmetrically — `/health` reports
`degraded` honestly rather than crashing (AC1.5). **Evidence:** degradation tests assert no 5xx;
runtime-demote tests in `tests/test_services.py`.

### Security guards — **added**
**Why:** a public RAG endpoint invites prompt injection. **How:** week-6 `InputGuard` (prompt-injection
regex, tightened to avoid false refusals on real FastAPI questions like "I always forget…") on both
`/query` and `/query/stream`, polite structured refusals (200, not 500); `OutputValidator` PII pass on
agent output. **Evidence:** 10-injection / 5-benign suite; a soak injection refused as `200 + refused`,
never a 5xx.

### Sandboxed code executor (D6) — **added** (the augmentation, Week 6)
**Why:** the gap was that `CODE_GENERATION` answers were *unverified* — users still had to run the code.
**How:** AST denylist → `python -I` subprocess isolation (scrubbed env, temp-dir cwd, own process group)
→ `RLIMIT` CPU/AS/FSIZE → wall-timeout `killpg` → socket-guard prelude. Generated code self-verifies
in-process with `TestClient` (D7) so "running" never binds a port. **Honest limit:** single-box —
full filesystem *reads* are still possible; the documented production-grade path is a Docker backend
(`--network none --memory 256m`). **Evidence:** 11-case safety suite (loop killed, network blocked,
denylist pre-exec, temp-dir isolation); full write-up in [`augmentation-decisions.md`](augmentation-decisions.md).

### Playground (D11) — **added, with a threat model**
**Why:** turns the agent's sandbox into a user-facing "now *you* tweak it" surface — the strongest demo
beat. **Threat model for user-submitted code:** identical AST-scan + sandbox path as the agent, plus
caps (10 KB, 15 s wall, 3 runs/min/session), no secrets in the subprocess env, and a `PLAYGROUND_ENABLED`
kill switch that 404s the endpoint without a redeploy. The only non-class dependency (`streamlit-monaco`),
contained to one view with a `st.text_area` fallback. **Evidence:** oversize / rate-limit / denylist /
disabled-404 guard tests.

### T3 two-stage LLM routing — **skipped** (honest cost/benefit)
**Why skipped:** T3 was competitive on retrieval in Week-3 but added **~34 s** of latency from the extra
LLM routing hop — unacceptable for an interactive learning tool, and the Week-4 eval showed T1b already
wins *answer quality* (T3's edge is exact-file retrieval, which the LLM judges can't even see). Production
runs **T1b**. See [`retrieval-strategy.md`](retrieval-strategy.md).

## Observability — Opik (D8)

**Added.** A thin shim (`app/observability.py`) makes Opik fully optional: every helper
decides at *call* time whether to trace, so with the key unset or Opik down, every other
AC still passes (AC1.8). It's wired four ways, each with dashboard evidence below (project
`fastpilot`, workspace `sunkanmi-daniel`; screenshots in [`opik/`](opik/)).

**1. Distributed tracing** — `@track` spans on the hot path (`rewrite_if_needed`,
`cache-lookup`, `classify`, `retrieve`, `generate`) nest under a parent `rag-query` /
`rag-query-stream` trace; `set_thread_id` groups a conversation's traces into one thread.
The Phase-4 evals alone produced **48 traces / 210 spans at a 0% error rate** (p50 7.5s).

![Project overview — 48 traces, 0 errors, latency + per-span volume](opik/01-dashboard-overview.png)
![Traces — rag-query + agent traces, 0% error rate](opik/02-traces-list.png)
![Spans — generate / retrieve / classify / cache-lookup / rewrite_if_needed with structured I/O](opik/03-spans-list.png)
![Span waterfall — one rag-query trace, nested spans](opik/04-span-waterfall.png)
![Threads — set_thread_id conversation grouping (the 6-message path-param follow-up chain)](opik/05-threads.png)

**2. Prompt versioning + hot-swap** — `register_prompts()` (now called explicitly in the app
lifespan) pushes each generation template to Opik's prompt library at startup (auto-versions on
change); `fetch_prompt()` pulls the latest at runtime (60s cache), so an edit in the Opik UI is
picked up on the next request with no redeploy. The flag is read through the module at call time,
so startup config is seen (a value-import would freeze it False).

Verified server-side via the Opik prompt API — all 4 templates registered and versioned
(commit hashes in [`opik/prompt-versions.json`](opik/prompt-versions.json)):
`rag-factual` `dd7b0a4e` · `rag-how-to` `747b4afd` · `rag-troubleshooting` `dd5a023e` ·
`rag-code-generation` `0fe056e6`. **Note:** Comet Cloud's *Prompt library UI* did not render
these SDK-registered prompts (a pre-existing prompt didn't show either — a platform rendering
quirk, not a registration failure); the API list endpoint returns all of them, and the runtime
`fetch_prompt → get_prompt` hot-swap path is confirmed live. The JSON above is the authoritative
evidence; `06-prompt-library.png` is optional if the UI later renders. The **Prompts tab on a
live trace** is the stronger proof that versioning is wired end-to-end — it shows the exact
prompt version attached to a `rag-query-stream` generation (verified: the trace context survives
the `asyncio.to_thread` hop where `build_prompt` runs, so the link lands on the right trace).

![Linked prompt on a live rag-query-stream trace (Prompts tab)](opik/06b-linked-prompt-trace.png)
![Prompt library — registered prompts + version history (if the UI renders)](opik/06-prompt-library.png)

**3. Feedback linking** — thumbs up/down → `/feedback` → `log_feedback_score` attaches a
`user_feedback` score to the answer's trace (joined by `trace_id`), closing the loop from a
user reaction back to the exact generation.

![Feedback score linked to its trace](opik/07-feedback-score.png)

**4. Online evaluation rule** — `fastpilot-hallucination`, an LLM-as-judge rule (the class
`_trigger_eval` pattern), samples a fraction of live `rag-query` traces and scores each for
hallucination, so production traffic is continuously evaluated without a batch job. It's doing
real work: across sampled traces most score `Hallucination=0.0` (faithful to the retrieved
context) but at least one scored **`0.85`** — the rule flagged a likely hallucination on live
traffic, which is exactly the signal a production guardrail should surface.

![Online evaluation rule scoring live traces (one flagged at 0.85)](opik/08-online-eval-rule.png)

## Deployment

**Railway, two services in one project** (class week-5 target):
- **`frontend`** (Streamlit) — the **only** service with a public domain.
- **`backend`** (FastAPI) — **private**, reached by the frontend at `backend.railway.internal`; no
  public domain, so only the UI is internet-facing.
- Each service has its own `Dockerfile` and binds Railway's injected **`$PORT`** (`uvicorn … --port
  $PORT` / `streamlit … --server.port $PORT`) — hardcoding 8000/8501 is the #1 first-deploy failure,
  avoided here. Backend healthcheck on `/health`, restart-on-failure.

**State is managed, not deployed** (D4): conversation memory + semantic cache live in **Redis Cloud**,
the corpus in **Qdrant Cloud** — both reached over TLS, both the same instances dev uses. Nothing
stateful runs in a Railway container.

**Secrets** are set in the Railway dashboard, never in the repo: backend gets `QDRANT_URL/API_KEY`,
`GOOGLE_API_KEY`, `VOYAGE_API_KEY`, `REDIS_*` (TLS), `OPIK_*`; frontend gets `API_BASE_URL=
http://backend.railway.internal:<PORT>`. `.env` and `.streamlit/secrets.toml` are git- and
gitingest-ignored.

**Local dev & CI parity:** `docker compose up backend frontend` mirrors the two-service topology
against the same managed Redis/Qdrant; a profiled `redis-stack` container (port 6380) is a
RediSearch stand-in for `pytest -m integration` only — it is never used by the running app.

**Accepted tradeoff — cache-lookup RTT:** using managed Redis Cloud (vs an in-cluster Redis) adds a
network round-trip to every cache lookup. We accept it: the cache embeds the query *once* and reuses
that vector (no extra Voyage cost), the managed instance removes an ops burden, and the economics
still favour a hit (a cached answer is ~$0 + one RTT vs a full Voyage-rerank-Gemini generation).

> **AC5.4:** deployed `/health` reports healthy and chat + agent mode stream end-to-end through
> Railway's proxy — verified on the public URL before recording the demo (SSE must arrive
> token-by-token, not as one buffered blob).
