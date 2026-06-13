# Scoping — FastPilot (a FastAPI learning companion)

A learning companion for FastAPI, built as a production RAG system over the official docs, the
full-stack template, and real GitHub threads. Three modes form one learning loop:
**Understand → Watch → Practice**.

## IDENTIFY — the problem
Learning FastAPI is **fragmented and unverified**. The knowledge a learner needs is scattered across
three places that don't talk to each other:
- the **official docs** (reference + tutorials),
- **example repos** like the full-stack template (idiomatic, real-world wiring), and
- **GitHub issues / discussions** (the "why doesn't this work?" long tail).

Worse, **reading doesn't prove you understood it.** You can read the path-parameter docs and still
write an endpoint that 500s. The only way to *verify* understanding is to **run code** — and that
means leaving the docs, setting up a project, and debugging on your own. Nothing closes the loop
from "I read it" to "I ran it and it works."

## QUALIFY — the user, and the evidence they're real
The user is a developer learning FastAPI by building — and **the builder is learner #1**. This isn't a
hypothetical persona: the project is **dogfooded**. Every real interaction is auto-logged (to a
gitingest-invisible JSONL at the repo root) and harvested into
[`../evaluations/dogfood_log.md`](../evaluations/dogfood_log.md), which is genuine
usage evidence — it shows conditional rewrite resolving real follow-ups ("can it be an integer?" →
"Can a query parameter with a default value be an integer?") and the semantic cache serving repeats,
in real traffic rather than in tests. The need is concrete because the builder hit it firsthand.

## DEFINE — the solution: an Understand → Watch → Practice loop
Three modes, each closing a different part of the gap:

| Mode | Loop stage | Closes the gap by… |
|------|-----------|--------------------|
| **Chat** | *Understand* | cited, grounded answers from the corpus — one place instead of three tabs |
| **Agent** | *Watch* | the agent **writes, runs, and self-corrects** working FastAPI code in a sandbox, with citations — turning "here's a snippet" into "here's a snippet that provably runs" |
| **Playground** | *Practice* | the learner edits the agent's code (or their own) and runs it in the same sandbox, with "Fix-with-AI" when stuck |

The augmentation (Agent + Playground) directly answers the *unverified-code* half of the problem:
`CODE_GENERATION` answers used to be unchecked; now they're executed and proven
(see [`augmentation-decisions.md`](augmentation-decisions.md)).

## SCOPE — corpus boundaries (what's in, what's out)
**In scope** — 4 sources chosen so each maps to a learning need, **514 documents → 4,232 chunks** in
the production collection `rag_accelerator_capstone_final`:

| Source | Learning need it serves |
|--------|-------------------------|
| **Official FastAPI docs** | the canonical *how* — reference + tutorials |
| **Full-stack FastAPI template** | idiomatic, production wiring (auth, structure, deployment) |
| **GitHub issues** | the troubleshooting long tail — real errors and fixes |
| **GitHub discussions** | design questions and community patterns |

Chunking and embedding choices for this corpus are in [`chunking-strategy.md`](chunking-strategy.md);
retrieval over it in [`retrieval-strategy.md`](retrieval-strategy.md).

**Out of scope (deliberately):** other Python web frameworks; non-FastAPI Pydantic usage; running the
learner's *full* multi-file projects (the sandbox is single-file, no DB, no network — an honest limit,
not an oversight); and any feature needing user identity (e.g. a "previous conversations" browser),
since the app ships without auth.
