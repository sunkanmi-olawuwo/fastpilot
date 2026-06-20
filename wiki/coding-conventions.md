# Coding Conventions

> The house style this codebase already follows. When you add code, match what's here —
> these are observations of the existing source, not aspirations. Enforced bits are flagged
> **(lint)**. See also [[testing-strategy]] and [[component-architecture]].

## Language + typing
- **Python 3.11–3.13.** Every module starts with `from __future__ import annotations`.
- Modern type hints throughout: `str | None`, `list[dict[str, Any]]`, `tuple[bool, Optional[str]]`.
- Public functions and dataclasses are fully annotated. Internal one-liners may use `# noqa: ANN`.

## Linting + formatting **(lint)**
Ruff, configured in `pyproject.toml`:
- `select = ["E", "F", "I", "B"]` (pycodestyle, pyflakes, isort, bugbear).
- `line-length = 120`, `target-version = "py311"`.
- Per-file ignores: `scripts/*.py` allow `E402`/`I001` (sys.path bootstrap before imports);
  `app/prompts/templates.py` allows `E501` (prompt text is content, not code).
- `evaluations/eval_results/` is excluded (captured evidence, not source).
- CI runs `ruff check .` first (fast fail) then the test suite. Keep the tree ruff-clean.

## Documentation style
- **Module docstrings explain the *why* and the request/data flow**, not just the *what*
  (see `app/main.py`, `app/augmentations/code_executor.py`). Many reference internal
  decision IDs (e.g. "D6", "D8") — that's intentional traceability; keep the pattern when
  extending an existing module.
- **Inline comments justify decisions** ("Refusals are NOT written to conversation memory
  because…"), they don't narrate mechanics. Prefer a comment that explains a trade-off over
  one that restates the code.
- Honest limitations are documented in-place (e.g. the sandbox's residual-risk note), not hidden.

## Architecture patterns
- **App factory** — `create_app()` returns a fresh `FastAPI` so tests get isolated instances.
- **Dependency injection for testability** — services live on `app.state` and are reached via
  `get_*()` getters; tests inject fakes. The agent/executor take their collaborators as
  constructor args.
- **Cached singletons** — `get_settings()` is `@lru_cache`d; `get_input_guard()` lazily builds
  a singleton with precompiled regexes. Use this pattern for expensive, stateless objects.
- **Resilience by construction** — service getters **degrade internally and never raise**;
  health is reported via `is_healthy()`, not exceptions. New external dependencies must follow
  this (missing creds → degraded, not crash).
- **Don't block the event loop** — wrap synchronous service I/O in `asyncio.to_thread`, and
  overlap independent awaits with `asyncio.gather` (see `_prepare` in `main.py`).

## Configuration + secrets
- All config flows through `app/config.py` (`pydantic-settings`). **Every secret defaults to
  `""`** so the app imports cleanly without credentials — this is what keeps CI hermetic.
- Never read `os.environ` directly for app config; add a field to `Settings` instead.
- Env var names are UPPERCASE; pydantic maps them case-insensitively.

## Naming
- **Files:** snake_case for Python modules; **kebab-case** for docs/wiki pages
  (e.g. `endpoint-summary.md`).
- **Private helpers** are prefixed `_` (`_sse`, `_finalize_turn`, `_Services`).
- **Endpoint handlers** are small and delegate to traced core functions (`_run_query`,
  `_run_stream_setup`); shared logic is factored so the four query/stream × hit/miss paths
  can't drift (`_finalize_turn`).

## Error handling
- Boundary handlers catch broadly with `# noqa: BLE001`, log with `logger.exception`, and
  **hide internals unless `settings.debug`**.
- Expected rejections return a structured reason (a `guard` field, a refusal message), **not**
  a 5xx — only genuine failures raise `HTTPException` (`503`) / fall to the global `500` handler.

## Observability + logging
- Logging is configured once (`logging_config.py`); use `logging.getLogger(__name__)`.
- Wrap traced units with `@track(...)` from `app/observability.py` — it's a no-op without Opik,
  so it's always safe to add.
- Log lines are concise and structured (`session=%s msg=%s type=%s …`) and truncate session
  IDs to 14 chars.

## Commits
- Imperative subject; explain the *why* in the body for non-trivial changes (mirror the
  existing `git log`).
- Co-author trailer is used for AI-assisted commits.
