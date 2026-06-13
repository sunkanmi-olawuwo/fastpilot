# What's remaining (final-stretch checklist)

> Working checklist — **not** part of the graded submission (gitingest-ignored). Everything
> below is **deploy-time / manual** and needs your Railway account, a browser, or the recorder.
> All code, docs, evals, and tests are done and committed.

Two `prequalify.py` checks are still FAIL, and both clear once the steps below are done:
- ❌ **No video link in `submission.md`** → clears at step **C**.
- ❌ **No submission `.txt` in repo root** → clears at step **E**.

---

## A. Deploy to Railway  *(follow [`DEPLOY.md`](DEPLOY.md))*
- [ ] New Railway project → deploy from this GitHub repo.
- [ ] **backend** service → Root Directory = `final-submission/app` (uses `app/railway.toml` + Dockerfile).
- [ ] **frontend** service → Root Directory = `final-submission/frontend`.
- [ ] Set env vars per service (full list in `DEPLOY.md`): backend = Qdrant/Google/Voyage/Redis/Opik
      + `QDRANT_COLLECTION=rag_accelerator_capstone_final`, `CACHE_DISTANCE_THRESHOLD=0.16`;
      frontend = `API_BASE_URL=http://backend.railway.internal:${{backend.PORT}}`.
- [ ] Generate a **public domain on the frontend only**; backend stays private.

## B. Verify the deployment  *(AC5.4–AC5.6)*
- [ ] `/health` → `{"status":"healthy"}` (all components).
- [ ] Public frontend URL: **chat streams token-by-token** through Railway's proxy (not one buffered blob).
- [ ] Agent mode writes → runs → self-corrects on the live URL.
- [ ] **Real-phone pass** over the public URL (closes AC2.1 against production).
- [ ] Pre-demo warmup: hit `/health` + one query ~5 min before recording.

## C. Demo video + transcript  *(Video 10%)*
- [ ] Record a **< 3-min** Loom against the **deployed URL**. Beats: Q1 chat + citations · Q2 follow-up/cache
      hit · Q3 agent run · Q3b Playground (tweak the agent's code, re-run).
- [ ] Paste the Loom link under **Demo Video** in `submission.md`. *(clears prequalify FAIL #1)*
- [ ] Fill the sections in `video-transcript.md`.

## D. Opik dashboard screenshots
- [ ] Save the PNGs into `docs/opik/` with the names in [`docs/opik/README.md`](docs/opik/README.md):
      `01-dashboard-overview`, `02-traces-list`, `03-spans-list`, `04-span-waterfall`, `05-threads`,
      `06b-linked-prompt-trace`, `07-feedback-score`, `08-online-eval-rule`. *(`06` is N/A — Comet UI quirk.)*
- [ ] `git add final-submission/docs/opik/*.png`.

## E. Final packaging
- [ ] From repo root: `uv run gitingest final-submission/ -o sunkanmi_olawuwo_final_submission.txt`
- [ ] `uv run python final-submission/prequalify.py` → **exit 0**, no FAILs, warnings reviewed
      (≤80 files, 5KB–1MB, no secrets). *(clears prequalify FAIL #2)*

## F. Push everything
- [ ] `git push` — this session's commits are local on `main`; push so Railway + graders see the latest.

---

### Already done (no action) — for reference
Phases 0–4 complete; all Phase-5 docs written + grader-reviewed; sandbox hardened; concurrent-load
validated; live-app fixes (citations/overflow, light-dark toggle, Opik prompt registration); deploy
config (`railway.toml` ×2 + `DEPLOY.md`). Evidence in `evaluations/eval_results/`. 200 hermetic +
12 visual tests green, ruff clean.
