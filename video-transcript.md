# Video Transcript & Recording Script

> A **< 3-minute** screen recording against the **deployed public URL**. This file doubles as the
> **teleprompter** (read the **SAY** lines aloud) and the **submitted transcript** (the SAY lines are
> the transcript). Target ~2:45 so you stay under 3:00. Do one practice run first.

## Before you hit record (warmup)
- Open the **public frontend URL** (deployed — see `DEPLOY.md`). Sidebar expanded so the mode switcher shows. Pick light *or* dark and stay there.
- **Warm the models:** hit `/health` and run one throwaway query ~5 min before recording, so the first demo answer streams fast instead of cold-starting.
- Have these **paste-ready** (typing on camera wastes seconds):
  - **Chat:** `How do I add JWT authentication to a FastAPI app?`
  - **Follow-up:** `can I make the token expire?`
  - **Agent:** `Write and run an endpoint that validates a user payload with Pydantic and returns 422 on bad input.`
- Close other tabs/notifications. Record at 1280-wide so the UI matches the screenshots.

---

## Product Name
**FastPilot** — *Learn FastAPI, fast.*

## Problem Setup
**[0:00 · ON SCREEN: the welcome screen — "Learn FastAPI by building."]**

> **SAY:** "Learning FastAPI is fragmented — the official docs, example repos, and GitHub issues all
> live in different places, and reading them never proves you actually understood anything. This is
> **FastPilot**: a production RAG system that closes the loop from reading to running, in three modes —
> **Chat** to understand, **Agent** to watch, and **Playground** to practice."

## System Design
**[0:20 · ON SCREEN: stay on the welcome screen (or flash the architecture diagram from the README)]**

> **SAY:** "The frontend is Streamlit; it talks to a FastAPI backend over server-sent events. Every
> question runs through **hybrid retrieval** in Qdrant — dense Voyage embeddings plus BM25, fused and
> then **reranked** — and **Gemini 2.5 Flash** writes a cited answer. Redis holds conversation memory
> and a semantic cache, and **Opik** traces every call."

## Live Demo

### Q1 — Chat: cited answers
**[0:40 · ON SCREEN: Chat mode. Send: "How do I add JWT authentication to a FastAPI app?"]**

> **SAY:** "Let's ask how to add JWT auth. The answer streams in token by token, and every claim
> carries a **numbered citation** back to its source — here, the `OAuth2PasswordBearer` scheme straight
> from the official docs. I can open the sources to see exactly what it grounded on."

### Q2 — Follow-up rewrite + semantic cache
**[1:05 · ON SCREEN: send the follow-up: "can I make the token expire?"]**

> **SAY:** "Now a vague follow-up — *can I make the token expire?* Watch the **'↻ searched as'** line:
> it rewrites my question into a standalone query before retrieving, using the conversation so far. And
> if I ask something it's already answered, it comes back **instantly from the semantic cache** — no
> second model call."

### Q3 — Agent: write → run → self-correct (the differentiator)
**[1:30 · ON SCREEN: switch to Agent. Send: "Write and run an endpoint that validates a user payload with Pydantic and returns 422 on bad input."]**

> **SAY:** "Here's what makes it more than a chatbot. I'll ask the **Agent** to write *and run* an
> endpoint that returns 422 on bad input. Follow the timeline: it plans, retrieves grounding, writes
> code, and runs it in a **sandbox**. The first attempt **fails an assertion** — and instead of giving
> up, it reads the traceback, **fixes the code, and re-runs to exit zero**. That self-correction loop
> takes first-attempt success from about **50% to 100%** across our ten evaluation tasks."

### Q3b — Playground + close
**[2:20 · ON SCREEN: click "Send to Playground", change a value in the editor, click Run]**

> **SAY:** "And I can send that exact code into the **Playground**, change it myself, and re-run it in
> the same sandbox. Everything here is measured — production faithfulness came out at **0.992** — and
> I'm honest about the limits: the sandbox is in-process defense-in-depth, with Docker isolation as the
> documented next step. That's **FastPilot — learn FastAPI, fast.**"

**[~2:45 · END — stop recording]**

---

### Timing cheat-sheet
| Beat | Mark | Budget |
|---|---|---|
| Hook + product | 0:00 | ~20s |
| System design | 0:20 | ~20s |
| Q1 Chat + citations | 0:40 | ~25s |
| Q2 follow-up + cache | 1:05 | ~25s |
| Q3 Agent self-correct | 1:30 | ~50s |
| Q3b Playground + close | 2:20 | ~25s |

**If you run long:** trim the System Design paragraph to one sentence and drop the "open the sources"
aside in Q1 — that buys ~20s and keeps it under 2:30.
