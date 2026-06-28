## Introduction
**[ON SCREEN: the welcome screen — "Learn FastAPI by building."]**

This presentation is my final capstone submission for the Engineer's RAG Accelerator course.

The problem FastPilot tackles is this: learning  or working with a framework or language is fragmented. The knowledge you need is scattered across at least three places:

- the official docs,
- example repos on GitHub, and
- GitHub issues.

Each lives somewhere different, and reading them in isolation never proves you've actually understood anything.
FastPilot closes that loop. It's a RAG-based companion for learning FastAPI, with three modes:

- Chat — to understand,
- Agent — to watch worked examples get written, run, and self-corrected in real time, and
- Playground — to practice what you've learned.

## System Design 
**[ON SCREEN: flash the architecture diagram (README), then back to the app]**

The frontend is Streamlit, streaming from a FastAPI backend over server-sent events (SSE).

The retrieval path is not just a default — it's the result of a pairwise evaluation across configurations, and this one won: hybrid search in Qdrant — dense Voyage embeddings fused with BM25 lexical search — followed by a reranking pass. A two-stage, LLM-routed retriever matched it on quality but added roughly 30 seconds per query, so I cut it: worth building to find the ceiling, not worth shipping.

The rest of the stack:

Gemini 2.5 Flash handles generation.
Redis backs both conversation memory and a semantic cache — so repeat questions don't pay the full retrieval cost twice.
Opik is the observability and eval layer — tracing every call end-to-end, plus prompt versioning, feedback scores, and an online-eval rule.
The whole application ships as two services — packaged with uv, containerized with Docker, deployed on Railway.

## Live Demo

### Q1 — Chat: cited answers
[ON SCREEN: Chat mode. Send: "How do I add JWT authentication to a FastAPI app?"]

The answer streams in token by token — and every claim carries a numbered citation back to its source. Here, the OAuth2PasswordBearer scheme, straight from the official docs. I can open the sources and see exactly what it grounded on.

### Q2 — Follow-up rewrite + semantic cache
[ON SCREEN: send the follow-up: "can I make the token expire?"]

Now a deliberately vague follow-up — can I make the token expire? Watch the "searched as" line: before retrieving, it rewrites my half-question into a standalone query using the conversation so far. And if I ask something already answered, it comes back instantly from the semantic cache — no second model call.

### Q3 — Agent: write → run → self-correct (the differentiator)
[ON SCREEN: switch to Agent. Send: "Write and run an endpoint that validates a user payload with Pydantic and returns 422 on bad input."]

This is what makes it more than a chatbot. The Agent runs a deterministic, code-driven loop — not free-form tool-calling. Follow the timeline: it plans, retrieves grounding, writes code, and runs it in a sandbox. The first attempt fails an assertion — and instead of giving up, it reads the traceback, fixes the code, and re-runs to exit zero. That self-correction loop took first-attempt success from about 50% to 100% across the ten evaluation tasks.

### Q3b — Playground + close
[ON SCREEN: click "Send to Playground", change a value in the editor, click Run]

And I can send that exact code into the Playground, change it myself, and re-run it in the same locked-down sandbox — AST-scanned, no network, no secrets. Everything here is measured: production faithfulness came out at 0.992. And I'm honest about the limits — that sandbox is in-process defense-in-depth, with Docker isolation as the documented next step.

That's FastPilot. Learn FastAPI, fast.


**[END — stop recording]**