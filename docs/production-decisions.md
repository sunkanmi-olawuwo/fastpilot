# Production Decisions (Week 5)

> **Status:** scaffold (Phase 0). Written in Phase 5. One entry per service: added/skipped, why, evidence.

## Services
_TODO: SSE streaming · semantic cache (+threshold experiment) · conversation memory + conditional
rewrite · query router · Redis degradation story · security guards · sandbox design ·
T3 routing skipped (34s) · Opik integration (tracing, prompt versioning, feedback, online eval) ·
Playground (D11) threat model._

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
_TODO: Railway 2-service topology (private backend) + managed Redis Cloud / Qdrant Cloud;
local docker-compose for dev; redis-stack container as CI test stand-in; cache-lookup RTT tradeoff._
