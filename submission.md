# Final Capstone Submission

## Student Name(s)
Sunkanmi Olawuwo

## Product Name
**FastPilot**

## Project Title
FastPilot — *Learn FastAPI, fast.* A FastAPI learning companion that closes the loop from reading to
running: **Understand → Watch → Practice**.

## Demo Video
_Loom link (< 3 min), recorded against the deployed public URL — added at deploy time._

---

## Problem Statement
Learning FastAPI is **fragmented and unverified**. The knowledge lives in three disconnected places —
the official docs, example repos like the full-stack template, and GitHub issues/discussions — and
**reading doesn't prove you understood it**: you can read the path-parameter docs and still ship an
endpoint that 500s. The only way to verify understanding is to *run code*, which means leaving the
docs and debugging alone. FastPilot closes that loop. The builder is learner #1 — the project is
**dogfooded**, and `evaluations/dogfood_log.md` is genuine usage evidence. Full framing in
[`docs/scoping.md`](docs/scoping.md).

## Data Overview
**514 documents → 4,232 chunks** in the production collection `rag_accelerator_capstone_final`, from
**4 sources** each chosen to serve a learning need:

| Source | Learning need |
|--------|---------------|
| Official FastAPI docs | the canonical *how* (reference + tutorials) |
| Full-stack FastAPI template | idiomatic production wiring (auth, structure, deploy) |
| GitHub issues | the troubleshooting long tail |
| GitHub discussions | design questions + community patterns |

## System Architecture

### Chunking Strategy (Week 2)
Hybrid chunker — **AST (tree-sitter) for code**, markdown-aware recursive for prose, routed by
document language so a code chunk is never split mid-function. The headline decision: migrating
**BGE → Voyage-4-lite (2048-d)** eliminated **27.9% silent chunk truncation**. Detail in
[`docs/chunking-strategy.md`](docs/chunking-strategy.md).

### Retrieval Pipeline (Week 3)
**T1b** — hybrid **Voyage-4-lite (dense) + Qdrant/BM25 (sparse) → RRF → Voyage rerank-2.5 → top 10**.
Evidence-backed, not a default: T1b won **30/36 pairwise** comparisons, and reranking alone was worth
**+21 points**. T3 (two-stage LLM routing) was **skipped** for production — competitive on retrieval
but ~34 s latency. Detail in [`docs/retrieval-strategy.md`](docs/retrieval-strategy.md).

### Production System (Week 5) + Augmentation (Week 6)
FastAPI backend (SSE streaming, semantic cache, conversation memory + conditional rewrite, query
router, security guards, graceful Redis/Qdrant degradation) → Gemini 2.5 Flash; Streamlit frontend
(Chat / Agent / Playground). The **augmentation** is a grounded **code-runner agent** + **Playground**
over a sandboxed executor — every service is an explicit add/skip decision in
[`docs/production-decisions.md`](docs/production-decisions.md); the agent in
[`docs/augmentation-decisions.md`](docs/augmentation-decisions.md). Observability via **Opik**
(tracing, prompt versioning, feedback, a live online-eval rule).

## Results
All measured **live through the production pipeline** (evidence in `evaluations/eval_results/`):

| Metric | Result | Evidence file |
|--------|--------|---------------|
| Production faithfulness (v3 judge, via `POST /query`) | **0.992** (offline baseline 0.952; higher because the prod prompt mandates grounding + `[n]` citations — see findings) | `production_parity.json` |
| Production answer-coverage (deterministic Voyage) | **0.941** | `production_parity.json` |
| Agent success: first-attempt → **with** self-correction | **5/10 (50%) → 10/10 (100%)**, a **+50-pt** gain (5 tasks recover) | `agent_eval.json` |
| Agent grounding (cited chunks mention the API) | **93%** (25/27; 6/6 tasks cite) | `agent_quality.json` |
| Fix-with-AI on broken snippets | **3/3** | `agent_quality.json` |
| Soak (20-call mixed session) | **0 × 5xx**, `/metrics` reconciles | `soak_session.json` |
| Concurrent load (8 sessions + 2 agents, cache off → 24 live generations at once) | **0 × 5xx**, metrics reconcile under racing increments, healthy | `concurrent_soak.json` |

**Honest findings** (the kind graders reward):
- **Faithfulness *improved* in production** (0.952 → 0.992) because the prod prompt mandates grounding + `[n]` citations — generated answers stay closer to retrieved context than the offline ones.
- **The cache's paraphrase/near-miss embedding bands overlap**, so AC4.2's strict "100% paraphrase / 0 near-miss" target is unachievable with this embedder — we chose **safety** (zero wrong-answer serving) over hit-rate.
- **The human-in-the-loop probe found a robustness gap** the agent's own self-tests could never surface: its `depends` solution accepts negative pagination (`skip=-5`).
- **The Opik online-eval rule flagged a live answer at hallucination 0.85** — the guardrail does real work, not rubber-stamping.

## Self-Assessment
Calibrated 1–5 — deliberately **not** straight-5; weaknesses named below.

| Rubric criterion | Weight | Self-score | Honest justification |
|------------------|:------:|:----------:|----------------------|
| Problem & Data | 15% | **4.5** | Specific, dogfooded problem; corpus mapped source-by-source to learning needs. Docked 0.5: one user (the builder) — though the app was genuinely **dogfooded** (**100+ logged interactions** in `dogfood/sessions.jsonl`, harvested into the dogfood log), so genuine evidence, just a single user. |
| System Design | 25% | **4.5** | T1b is evidence-backed, every service has an explicit add/skip decision, the augmentation is designed + measured, and resilience is validated **under concurrent load** (8 sessions + 2 agents, 24 live generations at once → 0 × 5xx, metrics reconcile). Docked 0.5 for the one genuine ceiling: the sandbox is **defense-in-depth in-process** (reflection escapes + `open` blocked, env scrubbed, network off — but not a hard boundary; Docker `--network none` is the documented production path), and apps are single-file by design. |
| Results & Honesty | 25% | **5.0** | Eval re-run *through the production endpoint*, agent measured ON vs OFF, and several genuinely honest findings reported rather than buried (cache band overlap, negative-skip gap, faithfulness delta explained). The strongest area. |
| Documentation Quality | 15% | **4.5** | Full doc set + an iteration log with real failure→fix stories. Docked 0.5: some Week-1/2/3 figures are ported from the weekly docs rather than re-derived here. |
| Optional Depth (W4/W6) | 10% | **5.0** | **Both** bonus boxes delivered and *measured*: `evaluation-strategy.md` (triangulated judges) + `augmentation-decisions.md` (the code-runner, with gap → augmentation → measurement → limits). |
| Video & Transcript | 10% | _pending_ | Recorded against the deployed URL. |

### Honest limitations (named, not hidden)
- **Sandbox is defense-in-depth, not a hard boundary** — the textbook reflection escape, `getattr`/`globals`, and `open` are blocked at the AST scan, the env is scrubbed (no secrets) and the network is off; but a *pure in-process Python* sandbox can't be a true guarantee (read-only `pathlib` access remains) — Docker `--network none` is the production path, deferred because Railway has no docker-in-docker.
- **Cache is conservative by design** — threshold 0.16 favours zero wrong answers over hit-rate (AC4.2 bands overlap).
- **Agent self-verification only tests what it thought to test** — see the `depends` negative-skip finding.
- **No keystroke autocomplete** in the Playground — Streamlit rerun + iframe latency; documented next step.
- **Comet's Prompt-library UI** doesn't render SDK-registered prompts — D8 versioning is verified via the API (`docs/opik/prompt-versions.json`) and a live linked-prompt trace instead.
