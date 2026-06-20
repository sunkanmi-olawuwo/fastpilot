# Change / Session Log

Newest first. Append one entry per working session or notable change (see [[CLAUDE.md]]
rule 4). Keep entries short: what changed, why, and which wiki pages were touched.

---

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
