# FastPilot — *Learn FastAPI, fast.*

A learning companion for FastAPI, built as a production RAG system over the official
docs + full-stack template + GitHub issues/discussions. Three modes form a learning
loop: **Chat** (understand — cited answers) · **Agent** (watch — writes, runs, and
self-corrects code in a sandbox) · **Playground** (practice — edit and run code yourself).

> Build status: **Phase 0 — scaffolding.** The app, frontend, and agent land in
> Phases 1–3. See `__plans/final-capstone-phased-plan.md` (repo root) for the roadmap.

## Architecture

```
Streamlit frontend ──HTTP/SSE──> FastAPI backend ──> Qdrant Cloud (hybrid retrieval)
                                          │            Voyage (embed + rerank-2.5)
                                          │            Gemini 2.5 Flash (generate)
                                          ├──> Redis Cloud (conversation + semantic cache)
                                          └──> Opik (tracing, prompt versioning, feedback)
```

## Prerequisites (accounts + keys)

Copy `.env.example` → `.env` (repo root) and fill in:

| Service | Vars | Where |
|---|---|---|
| Qdrant Cloud | `QDRANT_URL`, `QDRANT_API_KEY` | https://cloud.qdrant.io |
| Google Gemini | `GOOGLE_API_KEY` | https://aistudio.google.com/apikey |
| Voyage AI | `VOYAGE_API_KEY` | https://dash.voyageai.com |
| **Redis Cloud** | `REDIS_HOST/PORT/PASSWORD` | https://redis.io/cloud — **enable "Search & Query"** |
| **Opik** | `OPIK_API_KEY`, `OPIK_WORKSPACE` | https://www.comet.com → Opik |

## Quickstart

```bash
# 1. Install deps (from repo root)
uv sync --extra dev

# 2. Verify environment, Qdrant collection, and Redis (creates the cache index)
uv run python final-submission/scripts/01_verify_environment.py
uv run python final-submission/scripts/02_verify_collections.py
uv run python final-submission/scripts/03_setup_redis.py

# 3. Run the stack locally (talks to Redis Cloud via ../.env)
cd final-submission && docker compose up backend frontend
#   backend → http://localhost:8000   (docs at /docs)
#   frontend → http://localhost:8501

# Or run the backend directly:
cd final-submission && uvicorn app.main:app --reload
```

## Tests

```bash
# Hermetic unit tests (default — no network, no keys, < 10s)
uv run pytest

# Integration tests — need the local RediSearch container (stand-in for Redis Cloud)
docker compose --profile test up -d redis-test
REDIS_HOST=localhost REDIS_PORT=6380 REDIS_SSL=false uv run pytest -m integration
```

## Submission packaging (Phase 5)

```bash
uv run gitingest final-submission/ -o sunkanmi_olawuwo_final_submission.txt
uv run python final-submission/prequalify.py   # must exit 0
```
