# Video Transcript

> Written version of the ~3-minute demo, recorded against the deployed app.
> Video: https://www.loom.com/share/a1d6bf3ee7c54e5c93de4ac8c280992f · Live app: https://frontend-production-3afb.up.railway.app/

## Product Name
**FastPilot** — *Learn FastAPI, fast.*

## Problem Setup
When you're learning or working with a new framework, the knowledge you need lives in different places,
so you're constantly jumping from one tab to the next — and that context-switching is what makes
learning feel fragmented. FastPilot is a RAG-based **FastAPI learning companion** for developers
learning or working with FastAPI. It unifies the three scattered sources that knowledge normally lives
across — the **official FastAPI documentation**, **GitHub code examples**, and **GitHub issues and
discussion threads** — into a single, integrated learning and development environment. It has three
modes: **Chat** (ask anything about FastAPI), **Agent** (watch examples get written, run, and
self-corrected in real time), and **Playground** (practice and experiment with FastAPI yourself).

## System Design
A **FastAPI backend** talks to a **Streamlit frontend** over **server-sent events (SSE)**, which is
what gives the real-time, token-by-token streaming shown in the demo. Under the hood, retrieval is
**hybrid search in Qdrant** — dense **Voyage** embeddings fused with **BM25** keyword search — followed
by a **reranking pass**, and **Gemini 2.5 Flash** generates the answer. The key design decision is that
retrieval is hybrid + reranked (not a single method), and generation is grounded in the retrieved
chunks with inline citations so answers are verifiable rather than hallucinated.

## Live Demo

### Query 1: "How do I add JWT authentication to a FastAPI app?"
- **What happened:** Asked in Chat mode. The query ran through hybrid retrieval + reranking, and Gemini generated the answer, streamed token by token over SSE.
- **Result:** A grounded answer with code examples and **numbered citations** back to the source documents.
- **What this shows:** Real-time streaming and **grounding** — answers cite the docs, so you can see it isn't hallucinating.

### Query 2: "can I make it expire?" (vague follow-up)
- **What happened:** On its own the question is ambiguous, but the built-in **conditional query rewriting** used the conversation so far to rewrite it into a standalone question about **JWT token expiry** — shown as the "searched as" line right above the sources.
- **Result:** A focused answer on setting JWT token expiry.
- **What this shows:** **Conversation memory + query rewriting** handle real, context-dependent follow-ups instead of treating each turn in isolation.

### Query 3: "Write and run an endpoint that validates a user payload with Pydantic and returns 422 on bad input." (Agent mode)
- **What happened:** A deterministic, code-driven agent (not free-form tool calling): it **plans → retrieves grounding from the corpus → writes the code → runs it in a locked-down sandbox**. The first attempt failed; instead of giving up, the agent read the **traceback**, fixed the code, and re-ran it.
- **Result:** It **self-corrected to exit 0** — the code passed and the task completed. The generated code is shown.
- **What this shows:** The augmentation — **grounded, self-correcting code execution** in a sandbox, the piece that makes FastPilot more than a chatbot.

### Playground
- **What happened:** One click sends the agent's generated code into the **Playground**, where you run it yourself in the **same sandbox**.
- **What this shows:** Hands-on practice — the "do it yourself" stage that closes the learning loop (understand → watch → practice).

**Closing:** That's FastPilot — *learn FastAPI, fast.*
