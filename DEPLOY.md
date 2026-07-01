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

## Deploy gating (chosen policy)

**Straight from `main`, gated on CI.** No deploy branch, no PR-approval step (solo project) — but
a broken build must never reach production:

- In each Railway service → **Settings → enable "Wait for CI"** (check status before deploying).
  Railway then holds the deploy until the GitHub `ci.yml` checks pass on that commit. Push to `main`
  → CI runs ruff + tests → green → Railway deploys; red → no deploy.
- This reuses the existing CI as the gate, so there is **no GitHub Actions deploy workflow** to
  maintain (a `railway`-CLI deploy job would only duplicate the native integration).
- **During a demo/recording window:** flip the service to **manual deploy** (or just don't push) so
  the live app is a frozen, known-good build while you record.
- *(If this repo ever becomes collaborative and you want a hard approval gate, point Railway at a
  `production` branch and promote `main → production` via PR — not needed today.)*

## One-time setup (Railway dashboard)

1. **New Project → Deploy from GitHub repo** → pick this repo.
2. Add **two services** from the same repo:
   - **backend** — Settings → **Root Directory = `app`**. Railway finds
     `app/railway.toml` + `app/Dockerfile`. Healthcheck `/health` is already configured.
   - **frontend** — Settings → **Root Directory = `frontend`**.
3. **Env vars** (Railway dashboard → each service → Variables; never in the repo). Use the **same
   values as your local `.env`** — copy them straight across:
   - **backend:** `QDRANT_URL`, `QDRANT_API_KEY`, `GOOGLE_API_KEY`, `VOYAGE_API_KEY`,
     `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, `REDIS_SSL=true`, `QDRANT_COLLECTION=rag_accelerator_capstone_final`,
     `CACHE_DISTANCE_THRESHOLD=0.16`, `OPIK_API_KEY`, `OPIK_WORKSPACE`, `OPIK_PROJECT_NAME=fastpilot`,
     `PLAYGROUND_ENABLED=false` for staging or production unless you have explicitly accepted the risk.
   - **frontend:** `API_BASE_URL=http://backend.railway.internal:${{backend.PORT}}`
     (Railway's cross-service reference — resolves to the backend's injected port over the private network).
     `BACKEND_URL` is accepted as an alias if `API_BASE_URL` is unset; set the full base URL
     (scheme, no trailing slash). The client appends `/query`, `/health`, etc. Also set
     `PLAYGROUND_ENABLED=false` to hide Playground from the Streamlit sidebar.
4. **Public domain:** Settings → Networking → **Generate Domain on the `frontend` service ONLY**.
   Leave the backend with **no** public domain — it's reachable only at `backend.railway.internal`.
5. `$PORT` is handled — both Dockerfiles bind Railway's injected `$PORT`
   (`uvicorn … --port $PORT` / `streamlit … --server.port $PORT`).
6. **Gate on CI:** in each service → Settings → enable **"Wait for CI"** so a deploy only runs after
   `ci.yml` passes on that commit (see [Deploy gating](#deploy-gating-chosen-policy) above).

## Verify before recording the demo

- Backend (from the frontend, or a one-off `railway run`): `/health` → `{"status":"healthy"}`.
- Open the public frontend URL → **Chat streams token-by-token** (SSE must arrive incrementally
  through Railway's proxy, not as one buffered blob) → **Agent mode** writes/runs/self-corrects.
- **Real-phone pass** over the public URL (mobile layout).
- Pre-demo warmup: hit `/health` + run one query ~5 min before recording (warms the model clients).

## Record the demo (for the README + portfolio)

A short screen recording is what turns a 10-second README skim into a real look. Record against the
**deployed public URL** (Loom, or QuickTime → convert to GIF). Keep it **under 2 minutes**, hit these
beats, then paste the link into the two placeholders in `README.md` (live demo + walkthrough):

1. **Chat** — ask "How do I add JWT auth?" → show the streamed answer + a `[n]` citation.
2. **Follow-up** — a short follow-up that hits the conversation memory / semantic cache.
3. **Agent** — "Write and run a POST /items endpoint that returns the created item with HTTP 201,
   with a self-test asserting status 201" → show the timeline self-correct (Run → error → Fix &
   rerun → exit 0). This task reliably fails the first attempt then recovers (~6/7 runs), so the
   self-correct beat actually shows; do a dry-run first and re-run on the rare clean first pass.
4. **Playground** — tweak the agent's code and re-run it yourself.

For an animated hero GIF in the README, drop the file at `docs/screenshots/hero.gif` and swap the
`<img src="docs/screenshots/01-welcome.png">` tag at the top of `README.md` to point at it.
Talking points for the recording live in [`video-transcript.md`](video-transcript.md).

## Local parity
`docker compose up backend frontend` (from the repo root) mirrors this topology against the same
managed Redis/Qdrant — same Dockerfiles, so "works in compose" ≈ "works on Railway."

## GHCR images for SoloForge staging

The `publish-ghcr.yml` workflow builds the backend and frontend Docker images for VPS staging.
It does not replace Railway production deployment.

On pull requests, the workflow builds both images without pushing them. On push to `main`, or a
manual workflow dispatch, it publishes:

```text
ghcr.io/sunkanmi-olawuwo/fastpilot-backend:main
ghcr.io/sunkanmi-olawuwo/fastpilot-backend:sha-<short-sha>
ghcr.io/sunkanmi-olawuwo/fastpilot-frontend:main
ghcr.io/sunkanmi-olawuwo/fastpilot-frontend:sha-<short-sha>
```

Runtime secrets are still supplied by the target platform. Do not bake Qdrant, Redis, Voyage,
Google, or Opik credentials into the images.
