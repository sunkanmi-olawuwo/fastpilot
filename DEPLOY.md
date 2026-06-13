# Deploying FastPilot to Railway

**Two services in one Railway project** (class week-5 topology): a private `backend` (FastAPI)
and a public `frontend` (Streamlit). State is managed and external (Redis Cloud + Qdrant Cloud) —
nothing stateful runs in a Railway container.

## How it deploys — Railway's native GitHub integration (NOT GitHub Actions)

Railway connects to the GitHub repo directly and **auto-builds + deploys each service on every push**
to the connected branch, using each service's `Dockerfile` + `railway.toml`. There is **no deploy
GitHub Actions workflow** — and there shouldn't be:

- **`.github/workflows/ci.yml` stays CI-only** (hermetic tests + ruff). It never deploys.
- Railway's own pipeline does the build/deploy from the repo. This is the simplest, class-standard path.
- *(A GitHub Actions deploy via the `railway` CLI + a `RAILWAY_TOKEN` secret is possible, but it
  duplicates what the native integration already does and adds a secret + a workflow to maintain.
  Not used here.)*

So the deploy trigger is: **push to the branch Railway watches → Railway rebuilds the changed service.**

## One-time setup (Railway dashboard)

1. **New Project → Deploy from GitHub repo** → pick this repo.
2. Add **two services** from the same repo:
   - **backend** — Settings → **Root Directory = `final-submission/app`**. Railway finds
     `app/railway.toml` + `app/Dockerfile`. Healthcheck `/health` is already configured.
   - **frontend** — Settings → **Root Directory = `final-submission/frontend`**.
3. **Env vars** (Railway dashboard → each service → Variables; never in the repo):
   - **backend:** `QDRANT_URL`, `QDRANT_API_KEY`, `GOOGLE_API_KEY`, `VOYAGE_API_KEY`,
     `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, `REDIS_SSL=true`, `QDRANT_COLLECTION=rag_accelerator_capstone_final`,
     `CACHE_DISTANCE_THRESHOLD=0.16`, `OPIK_API_KEY`, `OPIK_WORKSPACE`, `OPIK_PROJECT_NAME=fastpilot`.
   - **frontend:** `API_BASE_URL=http://backend.railway.internal:${{backend.PORT}}`
     (Railway's cross-service reference — resolves to the backend's injected port over the private network).
4. **Public domain:** Settings → Networking → **Generate Domain on the `frontend` service ONLY**.
   Leave the backend with **no** public domain — it's reachable only at `backend.railway.internal`.
5. `$PORT` is handled — both Dockerfiles bind Railway's injected `$PORT`
   (`uvicorn … --port $PORT` / `streamlit … --server.port $PORT`).

## Verify before recording the demo (AC5.4–AC5.6)

- Backend (from the frontend, or a one-off `railway run`): `/health` → `{"status":"healthy"}`.
- Open the public frontend URL → **Chat streams token-by-token** (SSE must arrive incrementally
  through Railway's proxy, not as one buffered blob) → **Agent mode** writes/runs/self-corrects.
- **Real-phone pass** over the public URL (closes AC2.1 against production).
- Pre-demo warmup: hit `/health` + run one query ~5 min before recording (warms the model clients).

## Local parity
`docker compose up backend frontend` (from `final-submission/`) mirrors this topology against the same
managed Redis/Qdrant — same Dockerfiles, so "works in compose" ≈ "works on Railway."
