# FastPilot — *Learn FastAPI, fast.*

A learning companion for FastAPI, built as a production RAG system over the official
docs + full-stack template + GitHub issues/discussions. Three modes form a learning
loop: **Chat** (understand — cited answers) · **Agent** (watch — writes, runs, and
self-corrects code in a sandbox) · **Playground** (practice — edit and run code yourself).

> **Final submission.** All three modes (Chat / Agent / Playground) are live and tested;
> production RAG backend + Streamlit frontend, evaluated end-to-end through `POST /query`.

## Architecture

```
Streamlit frontend ──HTTP/SSE──> FastAPI backend ──> Qdrant Cloud (hybrid retrieval)
                                          │            Voyage (embed + rerank-2.5)
                                          │            Gemini 2.5 Flash (generate)
                                          ├──> Redis Cloud (conversation + semantic cache)
                                          └──> Opik (tracing, prompt versioning, feedback)
```

## Key docs
Start with [`submission.md`](submission.md) (the full write-up + self-assessment). Then:

| Doc | Covers |
|---|---|
| [`docs/scoping.md`](docs/scoping.md) | the problem, the user, the corpus (Problem & Data) |
| [`docs/chunking-strategy.md`](docs/chunking-strategy.md) · [`docs/retrieval-strategy.md`](docs/retrieval-strategy.md) | chunking + the T1b retrieval pipeline |
| [`docs/production-decisions.md`](docs/production-decisions.md) | every production service as an add/skip decision + Opik + deploy |
| [`docs/augmentation-decisions.md`](docs/augmentation-decisions.md) · [`docs/evaluation-strategy.md`](docs/evaluation-strategy.md) | the agent augmentation + the triangulated eval (bonus) |
| [`docs/iteration-log.md`](docs/iteration-log.md) · [`evaluations/dogfood_log.md`](evaluations/dogfood_log.md) | build history (with real failure→fix stories) + real-usage log |

Measured results live in [`evaluations/eval_results/`](evaluations/eval_results/).

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

# 3. Run the stack locally (talks to Redis Cloud + Qdrant/Voyage/Gemini/Opik via ../.env)

#  Option A — Docker (mirrors the Railway two-service topology):
cd final-submission && docker compose up backend frontend --build

#  Option B — no Docker, two terminals (from the repo root):
#    Terminal 1 — backend (FastAPI → http://localhost:8000, docs at /docs):
.venv/bin/python -m uvicorn app.main:app --app-dir final-submission --port 8000 --reload
#    Terminal 2 — frontend (Streamlit → http://localhost:8501); run from frontend/ so the theme loads:
cd final-submission/frontend && ../../.venv/bin/python -m streamlit run app.py
```

> The frontend finds the backend via `API_BASE_URL` (default `http://localhost:8000`).
> `.env` is loaded by absolute path, so the working directory doesn't affect config.
> Note: after a repo move the venv's `uvicorn`/`streamlit` console scripts can carry a stale
> shebang — invoking via `python -m` (above) avoids it; `uv run uvicorn …` also works.

## Tests

```bash
# Hermetic unit tests (default — no network, no keys, < 10s)
uv run pytest

# Integration tests — need the local RediSearch container (stand-in for Redis Cloud)
docker compose --profile test up -d redis-test
REDIS_HOST=localhost REDIS_PORT=6380 REDIS_SSL=false uv run pytest -m integration
```

## Submission packaging

```bash
uv run gitingest final-submission/ -o sunkanmi_olawuwo_final_submission.txt
uv run python final-submission/prequalify.py   # must exit 0
```
