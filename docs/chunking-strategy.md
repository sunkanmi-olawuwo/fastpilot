# Chunking Strategy (FastPilot)

## Strategy

FastPilot uses a **hybrid chunker** that routes each document to a sub-strategy by language, rather than applying one splitter to a heterogeneous corpus:

- **Code (tree-sitter AST).** Python source files are split with a tree-sitter AST splitter that respects `def`/`class`/function boundaries. A code chunk is therefore never cut mid-function — the symbol-to-implementation linkage (e.g. `verify_password`, `create_access_token` in `backend/app/core/security.py`) stays intact, and indentation never straddles a chunk boundary into code that no longer parses.
- **Prose (markdown-aware recursive).** Markdown and text documents use a recursive splitter with a markdown-aware separator priority (`##`/`###` headers → fenced ```` ``` ```` code-block ends → paragraph → sentence → space), keeping doc sections and per-comment thread boundaries coherent.
- **Other code formats (line-based fallback).** YAML, shell, TOML, and Dockerfile content falls back to a line-based splitter — line boundaries are meaningful for these formats, which word-splitting would destroy.

Routing is data-driven: each `Document` carries `language` from the ingestion manifest, so the route is metadata-based, not heuristic. This matches the framework guidance for **MIXED** corpora — no single content type dominates (Markdown docs 31%, GitHub issues 39%, template ~11%, discussions 19%), so a "dominant type" splitter would force one type to be chunked badly. A pure recursive splitter respects prose but cuts mid-function in code; a pure semantic splitter is expensive (double-embedding) and fails on code, where syntax similarity is not semantic similarity.

## Configuration

The configuration that produced the production collection `rag_accelerator_capstone_final`:

| Setting | Value | Notes |
|---|---|---|
| Code chunk target size | 2048 non-whitespace chars | AST sub-strategy budget; holds a typical FastAPI `core/security.py` (~1.5K chars) as a single chunk. |
| Overlap | 0.10 (10%) | Keeps ~10% context bleed-over across chunks. |
| Embedding model | Voyage-4-lite | 2048-dimensional embeddings, 32K-token input window. |
| Vector store | Qdrant Cloud | Collection `rag_accelerator_capstone_final`. |

**Corpus and indexing.** The corpus is **514 documents across 4 sources** — `official_docs` (156, the FastAPI documentation site), `template_repo` (58, the Full Stack FastAPI Template), `github_issue` (200), and `github_discussion` (100). The hybrid chunker writes **4,232 chunks** (avg 8.23 chunks/document, ~222 words/chunk), routed as 81 code chunks and 4,151 markdown chunks.

## Key decision

**The BGE → Voyage-4-lite embedder migration is the headline.** Under the week-1 naive word-splitter, BGE-large (512-token window) silently truncated **27.9% of chunks (963 of 3,455)** — more than a quarter of the index lost content before it was ever embedded. The corpus drives this: GitHub issues have a median of 1,688 words and p90 of 4,030 words (~10× BGE's 512-token limit), and 80.5% of documents exceed that limit if not chunked.

Switching the new strategy to **Voyage-4-lite eliminates truncation entirely** — its 32K-token window is >60× BGE's, dropping truncation to **0** across all 4,232 hybrid chunks (a BGE re-run on the hybrid chunks would still have truncated 9.3%, so the embedder swap, not just the chunker, is what closes the gap).

The AST routing carries the complementary win: code chunks preserve `def`/`class` boundaries, so target template files like `security.py` are indexed as whole, parseable units rather than half-functions. Together — AST boundaries plus Voyage's wide window — the hybrid strategy indexes the full 514-document corpus with no silent content loss.
