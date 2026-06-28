# Change / Session Log

Newest first. Append one entry per working session or notable change (see [[CLAUDE.md]]
rule 4). Keep entries short: what changed, why, and which wiki pages were touched.

---

## 2026-06-28 — Demo polish: source titles/URLs, exec_result `ok`, reliable agent task

End-to-end demo-path verification surfaced three rough edges; all fixed and re-verified live.
- **Human-friendly sources.** `app/formatting.py` gains `source_title` + `source_url`, deriving
  `Advanced › Security › OAuth2 Scopes` and `https://fastapi.tiangolo.com/advanced/security/oauth2-scopes/`
  from the raw `official_docs::…/index.md` / `github_issue::N` labels (acronym-aware: OAuth2/API/JWT).
  `_format_contexts` ([app/main.py]) now emits `title` + `url` alongside `file_path`; the Chat and
  Agent sources panels ([frontend/app.py], [frontend/agent_view.py]) render the title as a link.
  All generated URLs verified `200`.
- **`exec_result.ok`.** The agent SSE `exec_result` event now includes `ok` (mirrors
  `ExecuteResult.ok`) so the UI doesn't re-derive success from `exit_code`
  ([app/augmentations/agent_orchestrator.py]).
- **Reliable demo task.** Empirically tested candidate Agent tasks against the real backend; the
  *"POST /items … returns the created item with HTTP 201, self-test asserts 201"* task fails the
  first attempt **6/7** runs (genuine AssertionError) and recovers **7/7** — so the fail→fix→exit-0
  beat actually shows on camera. Swapped it into `video-transcript.md` + `DEPLOY.md` (the old 422
  task succeeded first-try ~half the time; the password-confirm/EmailStr alternatives failed to
  recover and would show an honest failure). See [[endpoint-summary]] for the updated schemas.

## 2026-06-27 — Semantic cache fix: pin RESP2 so KNN lookups parse (was 0% hit rate)

End-to-end check against the real services found the semantic cache **never returned a hit** — it
connected, reported healthy, and *wrote* entries (`num_docs` climbed), but every `/query` came back
`cache_hit: false`. Root cause: Redis Cloud is now **Redis 8.4 (RESP3 by default)**, and **redis-py
8.0**'s `FT.SEARCH` result parser misreads the RESP3 response map when `decode_responses=False`
(its keys arrive as `bytes`), silently reporting **0 results** for every KNN query. The cache uses
`decode_responses=False` to read raw embedding bytes, so its lookup was permanently empty —
a silent 0% hit rate that `ping`/`is_healthy()`/`/health` all reported green (same green-degradation
class the DIM-mismatch guard already defends against).
- `app/redis_client.py`: `make_redis_client` now pins `protocol=2` (RESP2). Verified: the *only*
  variable — same index/data/query — `decode_responses=False` gives KNN `total 0` on RESP3 vs
  `total 1` on RESP2.
- Re-verified live after the fix: identical query → HIT `distance 0.0` in **722ms** (vs 7.7s miss),
  a **reworded** query → HIT `distance 0.056` (< 0.16 threshold, proves *semantic* match), unrelated
  query → correct MISS. `/metrics` hit-rate moved 0% → 50% across the 4-query probe.
- See [[component-architecture]] → *Resilience* and [[overview]] (Memory + cache row).

## 2026-06-21 — Sandbox suppresses Starlette's httpx-deprecation warning

Starlette 1.3+ emits a `StarletteDeprecationWarning` at `TestClient` import (it prefers an
`httpx2` package). Cosmetic, but it landed in every sandbox run's stderr — which the Agent and
Playground surface to learners.
- `app/augmentations/code_executor.py`: added a `-W` message filter to the sandbox argv. It must
  be `-W`, not `PYTHONWARNINGS`: the executor runs `python -I` (isolated mode), which ignores
  `PYTHON*` env vars, and a category filter can't import the starlette class at interpreter
  startup — so the filter matches on the message text.
- Regression test in `tests/test_executor.py` asserts the sandbox stderr stays clean.

## 2026-06-21 — Agent asserts on Pydantic v2 error `type`, not v1 `msg`

Prod symptom: the Agent's generated self-tests asserted on Pydantic **v1** error wording
(`"ensure this value is greater than 0"`), which never matches the **v2** sandbox
(`"Input should be greater than 0"`). The program failed its own `assert`, the ≤2-attempt
fix loop ([[component-architecture]]) couldn't recover, and the run surfaced as a failure.
- `app/prompts/templates.py`: `AGENT_CODE_PROMPT` now tells the agent the sandbox is Pydantic v2
  and to assert on the stable `err["type"]` (`greater_than`, `string_too_short`, `value_error`)
  rather than the reworded `err["msg"]`. `AGENT_FIX_PROMPT` gains a v1→v2 hint so the fix loop
  can repair a msg-substring assert if one slips through.

## 2026-06-21 — Frontend accepts `BACKEND_URL` as an `API_BASE_URL` alias

While deploying to Railway, the frontend couldn't reach the backend: the env var was set as
`BACKEND_URL`, but `frontend/api_client.py` only read `API_BASE_URL` (falling back to
`http://localhost:8000` — the frontend container itself).
- `frontend/api_client.py` now resolves the base URL as
  `API_BASE_URL` → `BACKEND_URL` → `http://localhost:8000`, using `or` so empty values fall
  through (matches the secrets-default-to-empty / degrade-don't-crash convention).
- `DEPLOY.md` notes the alias under the frontend env vars.

## 2026-06-20 — Wiki embeds design conclusions (links out, no file moves)

Decided to keep `docs/` (deep design essays, code-coupled) and `wiki/` (the living map) as two
cross-linked systems rather than merging them. To make the wiki self-sufficient for the *takeaways*:
- [[component-architecture]] now carries the **evidence conclusions** inline — T1b won 30/36 pairwise
  (+21 from rerank, T3 skipped ~34 s), chunking removed 27.9% truncation, and the agent's
  ≤2-fix loop lifts success ~50% → 100% — each with a **link out to the full essay**. Added an
  add/skip-decision pointer to the production-decisions essay.
- [[overview]] links the scoping essay (problem + corpus); [[feature-coverage]] links the chunking,
  retrieval, and evaluation essays. All link-outs are **absolute GitHub URLs** so they resolve in the
  published GitHub Wiki (relative `../docs/` paths don't).
- Also de-course-ified residual wiki references for consistency (`Week-6` → augmentation layer,
  `class CRAG` → CRAG, the `AC1.5` convention example → `D#` decision IDs).

## 2026-06-20 — De-course-ified the design docs

Removed coursework framing from the `docs/` design essays so they read as professional engineering
docs, **without touching any technical substance**:
- **Titles:** dropped `(Week 5)`, `(Week 6) — BONUS`, `(BONUS — Optional Depth)`.
- **Bodies:** neutralized course-week labels (Week 1–6), dropped acceptance-criteria IDs (`AC#`) while
  keeping their thresholds in plain words, removed rubric/grading/self-assessment/submission framing,
  and rephrased "the class …" → "the reference …". `iteration-log.md` section headings reframed from
  weeks to phases (Foundations / Production backend / Agent augmentation / Live evaluation / Security
  & load hardening).
- **Preserved verbatim:** all metrics, dates, file paths, model names, and the internal decision IDs
  (`D#`, `T1a/T1b/T2/T3`). Verified: zero real numeric tokens lost (only `AC#`/self-score bookkeeping
  removed), all 29 dates intact, no broken heading anchors. See [[feature-coverage]] for results.

## 2026-06-20 — Removed submission.md (course artifact)

- Deleted `submission.md` (the capstone write-up: student name + rubric self-assessment) — it read
  as coursework, not product. Its substantive content already lives elsewhere: results + honest
  findings in `README.md`, the full limitations list in [[feature-coverage]].
- Repointed the three README links (`Full write-up` → **Docs & architecture** wiki; self-assessment
  line → `wiki/feature-coverage.md`; Documentation-table row → the Developer wiki) and dropped the
  `submission.md` bullet from [[index]]. No dangling references remain.

## 2026-06-20 — Sidebar expanded by default + better screenshots

- **Frontend:** `initial_sidebar_state` flipped `collapsed → expanded` (`frontend/app.py`) so the
  Chat/Agent/Playground mode switcher + controls are visible on load.
- **Screenshots regenerated** via the `visual` suite and promoted to `docs/screenshots/` (used by
  `README.md`): the agent shot now shows the **populated, syntax-highlighted attempt-2 code** and the
  Playground shows the **fully-painted Monaco editor** (previously blank / "Loading…"), all with the
  expanded sidebar.
- **`tests/test_visual.py`:** waits added so captures fire after the agent's static re-render
  (Send-to-Playground button + code visible) and after Monaco paints (`_wait_monaco`); `_switch_mode`
  tolerates the now-expanded sidebar; mobile overflow tests `_collapse_sidebar` first (the expanded
  sidebar overlays the chips at 390px). 12 visual + 208 hermetic tests green.

## 2026-06-20 — GitHub Wiki published + CI auto-publish

- Published `wiki/` to the **GitHub Wiki** via `scripts/publish_wiki.py` (in-repo `wiki/`
  stays canonical; the GitHub Wiki is a generated mirror with a `_Sidebar` and `index → Home`).
- Added a **`publish-wiki` CI job** (`.github/workflows/ci.yml`): on push to `main`, after
  tests pass, it re-runs the publish script so the wiki never drifts from `wiki/`. Uses
  `contents: write` + `GITHUB_TOKEN`; idempotent (no-ops when unchanged). This very entry is
  the first edit auto-published by that job.

## 2026-06-20 — Wiki established + repo packaged as standalone product

**Context.** FastPilot was extracted from the capstone monorepo into its own standalone repo
(`final-submission/` → repo root, full Phase 0–5 history preserved via `git filter-repo`),
then published at `github.com/sunkanmi-olawuwo/fastpilot` (public, CI green).

**This session — created the developer wiki** under `wiki/`:
- Wrote [[overview]], [[component-architecture]], [[endpoint-summary]], [[coding-conventions]],
  [[testing-strategy]], [[feature-coverage]], and the [[onboarding]] article — all derived
  from the current source (`app/`, `tests/`, `pyproject.toml`), with inline Mermaid diagrams
  for the architecture, RAG pipeline, agent loop, sandbox layers, and request sequence.
- Captured `raw/openapi.json` — the live OpenAPI 3.1 contract (10 routes) — as the immutable
  API reference. See [[raw/README]].
- Created `wiki/plans/` (empty by design — see [[plans/README]]) and `wiki/assets/`.
- Added the wiki-maintenance rules to the repo's `CLAUDE.md`.

**Decisions.**
- Wiki lives in the **fastpilot** repo (not the monorepo).
- Historical course plans and any "plan-diverge" tooling were intentionally **left out** of
  scope; `wiki/plans/` starts fresh for future work.
- `docs/` (design essays) and `wiki/` (living dev map) are kept distinct — wiki links to docs
  rather than duplicating them.

**State.** Code/docs/evals/tests/CI green. Outstanding (owner-only): Railway deploy + demo
video — tracked in [[feature-coverage]].
