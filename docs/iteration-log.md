# Iteration Log

> **Status:** scaffold (Phase 0). Appended to as each phase lands (plan §11.1 learning packs feed this).

## Week 1–4 (ported)
_TODO (Phase 5): port progression from `week-{1,2,3,4}/docs/iteration-log.md`._

## Week 5 (production)
- 2026-06-11 — Phase 0 scaffolding: `final-submission/` skeleton, env + deps pinned, CI green from day 1.
- 2026-06-11 — Pre-commit review (7-angle) found 10 issues; all fixed: secrets ignore paths corrected in `.gitignore`/`.gitingestignore`, compose `env_file` made optional for fresh clones, placeholder detection deepened in the env gate, OS trust-store injection added to the script bootstrap (matches week-3/4 `_network.py`), smoke tests made truly hermetic, app refactored to a factory for Phase-1 testability, CI slimmed (ruff-first, pip cache, minimal installs) with the idle integration job deferred to Phase 1, and a requirements↔pyproject drift tripwire test added.
_TODO: porting decisions, threshold calibration, Redis Cloud choice, storyline pivot to learning companion._

## Week 6 (augmentation)
_TODO: agent iterations — keep at least one real failure→fix story; Playground + Fix-with-AI._
