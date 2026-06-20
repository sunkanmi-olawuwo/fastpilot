# CLAUDE.md — working agreement for this repo

Guidance for Claude Code (and humans) working in **FastPilot**. Read the developer wiki
in [`wiki/`](wiki/index.md) before substantial work — start with `wiki/onboarding.md`.

## Project at a glance
- Production **RAG** learning companion for FastAPI: Chat (understand) · Agent (watch) ·
  Playground (practice). Backend = FastAPI; frontend = Streamlit.
- Stack: Qdrant Cloud · Voyage (embed + rerank-2.5) · Gemini 2.5 Flash · Redis Cloud · Opik.
- See `wiki/overview.md` for architecture, `wiki/component-architecture.md` for the modules.

## Conventions
- Follow `wiki/coding-conventions.md` (typing, ruff `E/F/I/B` @ line-length 120, app-factory +
  DI, degrade-don't-crash, secrets default to `""`).
- Follow `wiki/testing-strategy.md`: default run is hermetic (`uv run pytest`); keep the
  **90% coverage gate** green; CI runs `ruff check .` then the suite.

## Wiki maintenance rules (keep `wiki/` alive)
1. **After any significant implementation work, update the relevant wiki page(s).**
2. **After ingesting new requirements or specs, create/update wiki pages** to capture them.
3. **Keep `wiki/index.md` current** — every page listed with a one-line summary.
4. **Keep `wiki/log.md` current** — append an entry for each session's work (newest first).
5. **Never modify `wiki/raw/`** — immutable source documents only (add a new dated file
   instead of editing an existing one).
6. **Page naming: kebab-case filenames** (e.g. `state-management.md`).
7. **Cross-reference pages with `[[Page Name]]`-style links.**
8. **If new work contradicts an existing wiki page, update it and note what changed**
   (in the page and in `wiki/log.md`).

## Don't duplicate
- `docs/` holds the original design-decision essays; `wiki/` is the living dev map. Link
  between them — don't copy content across.
