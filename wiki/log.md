# Change / Session Log

Newest first. Append one entry per working session or notable change (see [[CLAUDE.md]]
rule 4). Keep entries short: what changed, why, and which wiki pages were touched.

---

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
