# Retrieval Strategy

FastPilot retrieves over a 4,232-chunk index built from 514 harmonized documents across four sources (`official_docs`, `template_repo`, `github_issue`, `github_discussion`). The production retrieval path is **hybrid search → Voyage rerank → top-10 to the LLM**, the configuration (T1b) that won the Week-3 head-to-head. Every claim below is grounded in the Week-3 pairwise evaluation (`week-3/evaluations/week3_comparison.md`), and the live parameters are read from `app/config.py`.

## Hybrid search

Each query is embedded two ways and fused:

- **Dense:** Voyage `voyage-4-lite`, 2048-d, into the `text-dense` named vector. Its 32K-token window eliminated the silent truncation a smaller embedder would cause, so it was kept unchanged from the Week-2 winner.
- **Sparse:** `Qdrant/bm25`, into the `text-sparse` named vector. BM25 recovers exact-token recall the dense embedder misses on terminology-heavy queries (`pwd_context`, `OAuth2PasswordRequestForm`, `get_current_user`).

Both branches **prefetch 100 candidates** (`dense_prefetch=100`, `sparse_prefetch=100`) and are combined with Qdrant-native **Reciprocal Rank Fusion** (`FusionQuery(fusion=Fusion.RRF)`; rank constant k=60 — no score normalization, robust to the cosine-vs-BM25 scale mismatch). Explicit prefetch limits matter: Haystack's built-in hybrid retriever under-fetches (~10–20 docs/branch), starving the reranker's candidate pool. RRF then emits its top **50** candidates (`rerank_input=50` in config) — the set handed to the reranker.

In isolation, hybrid is roughly a wash: T1a (hybrid, no rerank) scored 22 pts vs the Week-2 dense-only baseline's 24 — BM25's recall is cancelled by its noise floor on this corpus. Hybrid's real value is as the **wide candidate net the reranker operates on**, not as a better top-10 by itself.

## Reranking

The 50 RRF candidates pass through **Voyage `rerank-2.5`** (cross-encoder, API-managed, 0–1 relevance scores), which returns the final **top 10** to the LLM (`rerank_top_k=10`). Unlike the bi-encoder retriever, the cross-encoder feeds each `(query, doc)` pair through a transformer together, scoring on actual word-by-word interaction.

Reranking is **the single biggest accuracy lever in the study**: T1b's 43 points vs T1a's 22 is a **+21-point jump** — nearly doubling the score. It promoted the highest-direct-contribution chunk to rank 1 on 8/12 questions (vs 1/12 without it) and eliminated all last-place finishes, for a latency cost of ~150ms (+1.4%; the Voyage rerank API call itself is ~50ms). If the Voyage call fails, the reranker falls back to the upstream RRF order truncated to `top_k`, so the pipeline survives reranker outages.

## Narrowing decision

**T1b (hybrid + Voyage rerank) is the production default.** In the Week-3 4-way pairwise eval (72 judge calls over 12 hold-out questions), T1b won **30 / 36** pairwise comparisons with **8 / 12 first-place finishes**, never finished last, and beat the Week-2 dense-only baseline by 19 points (43 vs 24).

**T3 (two-stage LLM file routing) was evaluated and deliberately skipped for the production default.** T3 narrows to ~12 LLM-selected files before hybrid+rerank, and it earns its keep on a narrow query family — it is the only technique to retrieve the actual `api/deps.py` implementation at rank 1 (Q12), and it wins the file-name and 422-error questions (Q6, Q12). But it costs **~34s/query** (the Stage-1 Gemini file-pruning call alone is ~20s) versus T1b's ~11s — roughly 3.3× the latency and ~10× the cost for wins on only that cluster. Honest cost/benefit call: not worth it as the default at our volume.

The honest split: **T1b wins answer quality, T3 wins exact-file retrieval.** On Q4 and Q8, T3 retrieved exactly the source files the questions named, yet the judge ranked T1b/T1a higher because it favours README/overview prose over raw code — the retrieval was correct, the evaluation of it was the gap. The Week-4+ direction is a query-shape router (T1b by default, T3 for explicit file-name queries) rather than one fixed strategy. (Technique 2, metadata/category filtering, was also built and evaluated; faithful class-style T2 landed 2nd at 39 pts vs T1b's 52 in the 5-way extension — confirming T1b as the default. The 5-way uses a 5-4-3-2-1 placement scale vs the 4-way's 4-3-2-1, which is why T1b's absolute points differ (52 vs 43) between the two comparisons.)

## Production wiring

Retrieval runs through `app/components/qdrant_hybrid_retriever.py` against the production collection **`rag_accelerator_capstone_final`** (`qdrant_collection` in config). That collection was re-indexed from the proven Week-3 hybrid pipeline (AST chunker, Voyage-4-lite dense, Qdrant/BM25 sparse, `text-dense`/`text-sparse` named vectors) to **4,232 chunks** carrying full `file_path` / `category` / `source` / `title` metadata, so the sources panel and exact-file probes have the payload they need. All retrieval parameters above are centralized in `app/config.py`, not hard-coded in the retriever.
