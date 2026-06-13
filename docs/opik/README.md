# Opik dashboard evidence — capture checklist

Screenshots from the **`fastpilot`** project (workspace `sunkanmi-daniel`) on Comet/Opik,
referenced by filename from [`../production-decisions.md`](../production-decisions.md).
Drop each PNG here with the exact name below.

| File | Status | Where in the Opik UI | What it proves |
|------|--------|----------------------|----------------|
| `01-dashboard-overview.png` | ✅ captured | Dashboards → Project overview | 48 traces, **0 errors**, p50 7.5s / p99 26.9s, per-span volume |
| `02-traces-list.png` | ✅ captured | Logs → Traces | 48 traces, 0% error rate, rag-query + agent traces |
| `03-spans-list.png` | ✅ captured | Logs → Spans | all instrumented spans: generate / retrieve / classify / cache-lookup / rewrite_if_needed |
| `04-span-waterfall.png` | ⬜ TODO | Logs → Traces → open one `rag-query` → span tree | the **nested** span tree (rag-query → rewrite → cache-lookup → classify + retrieve → generate) |
| `05-threads.png` | ✅ captured | Logs → Threads | `set_thread_id` conversation grouping (the 6-message path-param chain) |
| `06-prompt-library.png` | ⚠️ optional | Development → Prompt library | registered prompts + version history — **Comet Cloud UI didn't render SDK prompts**; authoritative evidence is [`prompt-versions.json`](prompt-versions.json) (4 prompts + commit hashes, confirmed via the API) |
| `06b-linked-prompt-trace.png` | ✅ captured | Logs → Traces → a `rag-query-stream` trace → **Prompts** tab | the live prompt version linked to a generation (D8 wired end-to-end — stronger than the library list) |
| `07-feedback-score.png` | ⬜ TODO | Logs → Traces → a trace with `user_feedback` | the thumbs feedback score linked to its trace |
| `08-online-eval-rule.png` | ✅ captured | Production → Online evaluation → Show logs | `fastpilot-hallucination` rule scoring live traces (mostly 0.0; one flagged at **0.85**) |

**Captured live:** 01–05, 06b, 07, 08 — the full Opik pass (tracing, spans, threads, linked
prompt, feedback score, online-eval rule). **`06`** (prompt-library UI) is N/A — Comet won't
render SDK prompts; `prompt-versions.json` is the authoritative D8 evidence. **Nothing remaining.**
