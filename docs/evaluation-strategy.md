# Evaluation Strategy (BONUS — Optional Depth)

FastPilot's evaluation treats the **measurement instrument** as a first-class
object, not just the RAG system under test. Earlier weeks ranked retrieval
techniques with a single pairwise Gemini judge; the open question was *how much
of that ranking is real and how much is one judge's bias*. This strategy answers
it by running three methods that measure different things and **triangulating**
them against a bootstrapped golden dataset — then, in Phase 5, re-running the
strongest method against answers generated **live by production** through
`POST /query` to prove the offline numbers hold in the deployed system.

The corpus is a FastAPI developer assistant over four heterogeneous sources
(`official_docs`, `template_repo`, `github_issue`, `github_discussion`) — a mix
of prose docs and Python source. That mix drives the method choice: code answers
need claim-level grounding checks that docs answers don't, and prior weeks showed
LLM judges quietly favouring docs chunks over code chunks. So we deliberately
pair a deterministic anchor with two independent LLM judges.

## Golden Dataset

- **Source:** 12 Q&A pairs (Q1–Q12) **bootstrapped from the two strongest
  systems** — Technique 1b (Hybrid + Voyage rerank) and Technique 3 (Two-Stage
  LLM routing + rerank). Reference answers are not hand-written; each is a real
  system output, and the chosen system's top-5 reranked chunks become the
  reference contexts.
- **Selection (deterministic + auditable):** for each question we scored *both*
  systems' answers for **self-groundedness** — the fraction of answer sentences
  attributable (Voyage rerank ≥ 0.5) to that system's own retrieved contexts —
  and kept the better-grounded answer. Ties (≤ 0.02) default to Two-Stage.
  Result: 6 answers from T1b, 6 from T3; **mean groundedness 0.938**.
- **Audit trail:** every sentence below the attribution threshold was flagged
  inline (`unsupported_sentences_for_review`) and manually inspected. All 25
  flags were markdown scaffolding, citation lines, or faithful paraphrases just
  under the strict 0.5 threshold — **no invented facts** — so none were removed.
  The flags are kept in the dataset as a transparency record.
- **Coverage:** the 12 questions span factoid/analytical/conceptual ×
  easy/medium/hard, all four sources, and both modalities (docs and code). Four
  questions (Q4, Q5, Q8, Q12) name a specific template file — the code-retrieval
  cases that separate the systems.

## Evaluation Methods (the triangulation)

Two methods is the course minimum; we run three (with two independent judges) so
the triangulation has a deterministic floor *and* a cross-model robustness check.

**Method 1 — Custom DECOMPOSED Gemini judge (`gemini-2.5-flash`), iterated v1→v2→v3.**
Measures answer quality (faithfulness via claim extraction + verification;
completeness via reference-criteria coverage) and, from v3, retrieval quality
(contextual precision as Average Precision; claim-based recall). Faithfulness is
claim-level because a fluent code answer that invents an API must score low even
when it reads well — a holistic score can't catch that. The prompt evolved with
*measured deltas on the same 12 questions* (all judged by Gemini at `temperature=0.1`):

| Version | Faithfulness | Δ | Completeness | Behaviour |
|---|---|---|---|---|
| v1 holistic single-score | 0.983 | — | 0.917 | inflated — 11/12 questions pinned at 1.0; one number hides which claim is ungrounded |
| v2 decomposed + verbatim-quote rule | 0.909 | −0.075 | 0.901 | inflation caught (faithfulness now varies 0.765–1.0), but the verbatim rule false-flagged faithful paraphrases of code (Q1 read 0.914 vs true 1.0) and shredded long answers (Q6 → 68 claims) |
| **v3 calibrated (final)** | **0.952** | **+0.043** | **0.893** | paraphrase tolerance + granularity guidance (15–30 claims, code blocks kept whole) + retrieval layer added; real gaps kept, false flags fixed |

The **why** behind each version is the evidence of judge design, not the final
number: v1's holistic score inflated and hid ungrounded claims; v2's
verbatim-quote requirement over-penalised faithful code paraphrases (Q1 claims
#20/#28/#33 wrongly marked unsupported) and gave inconsistent claim granularity
(Q6: 68 claims, many near-duplicate citation lines); v3 added (1) paraphrase
tolerance — a faithful semantic paraphrase counts as supported with the closest
quote cited, (2) granularity guidance — 15–30 atomic claims, code blocks one
claim, meta-statements excluded, and (3) the retrieval layer. The fixes are
provable: Q1 faithfulness went **0.914 → 1.000** and Q6 claim count **68 → 28**
(settling at 0.857 — *still* below 1.0, because Q6 has genuinely unsupported
claims v3 keeps flagged). v3's 0.952 sits deliberately **between** v1's inflated
0.983 and v2's over-strict 0.909 — calibrated, not regressed. (These are the
committed `decomposed_judge_t1b_hybrid_voyage.json` figures, the same v3 run that
feeds the triangulation and the production-parity baseline below.)

**Method 2 — Deterministic semantic metrics (Voyage `rerank-2.5`).** A
judge-independent anchor with no LLM in the loop, using the *same* reranker as
the production pipeline (threshold 0.5, k=10). It computes answer-coverage,
contextual precision/recall, MRR and nDCG, plus a **judge-free ground-truth
attribution check** (did the question's named `expected_file` / `expected_sources`
actually surface in the top-k?). When the two LLM judges disagree, this is the
tie-breaker. On the T1b reference system it reports `answer_coverage` **0.941**,
`contextual_precision` **0.983**, `ndcg@k` **0.958**, `mrr@k` **1.0** — and,
critically, `expected_file_hit_rate` **0.25** (T1b surfaces the *named* file in
only 1 of 4 code-file questions).

**Method 3 — Azure GPT-4o-mini cross-judge.** Runs the *identical* v3 rubric and
prompts as Method 1 but on a **different model family**, which avoids
self-preference / single-judge bias. Any conclusion that survives both judges is
robust; any that flips between them is flagged as judge-dependent.

**Triangulation = consensus across all three.** All three methods agree on the
overall system ranking — T1b > T3 > W2 — on aggregate composite
(semantic T1b **0.975** / T3 0.958 / W2 0.925; Gemini 0.927 / 0.920 / 0.808;
Azure 0.916 / 0.874 / 0.825). But unanimous *per-question* agreement is only
**2 / 12 (16.7%)**, and the two LLM judges agree on the per-question winner just
**60%** of the time. That disagreement is the point: it is exactly what a single
judge would have hidden, and it sets up the headline finding.

## Key Finding (the honest one)

**T1b wins answer quality; T3 wins exact-file retrieval — and the LLM judges
cannot see the exact-file distinction.** The two LLM judges rank T1b first on
answer quality and split heavily at the per-question level, but neither can tell
whether the *specifically named* ground-truth file was retrieved — they score
phrasing and grounding, not file identity. Only the deterministic
`expected_file_hit` check surfaces it: **T3 1.0 vs T1b 0.25 vs W2 0.0** on the
four code-file questions. So the "best" system depends on the task: T1b for
answer quality, T3 when the user needs the exact source file. This is the kind
of finding a single judge erases and triangulation recovers — reported here
rather than smoothed over. (Caveat: the file-hit gap rests on only four
questions, consistent with the Week 3 result but not high-powered.)

## Phase-5 Production-Parity Extension

The offline numbers above evaluate *bootstrapped* outputs. To prove they hold in
the deployed system, the **same v3 decomposed judge + Voyage semantic metric were
re-run on answers generated live by production through `POST /query` with the
cache OFF** — not offline, the real serving path.

| Metric | Week-4 offline T1b baseline | Phase-5 production (`POST /query`) | Δ |
|---|---|---|---|
| Faithfulness | 0.952 | **0.992** | **+0.040** |
| Answer coverage | 0.941 | **0.941** | 0.000 |
| Completeness | — | 0.825 | — |

Faithfulness **improved** in production (0.992 vs 0.952): the production prompt
**mandates grounding plus `[n]` citations**, so the live answers are *more*
strictly tied to retrieved context than the bootstrapped baselines. Answer
coverage is identical (0.941), confirming retrieval parity between the offline
study and the served pipeline. Per-question, 10 of 12 production answers score
faithfulness **1.0** (n=12, judge `gemini-2.5-flash`, gate 0.9). Evidence:
`final-submission/evaluations/eval_results/production_parity.json`.

**Agent-mode evaluation.** The agentic path (retrieve → answer → self-verify →
correct) was probed on 10 FastAPI concept tasks. Success rises from **0.5
first-attempt-only to 1.0 with self-correction** — a **+0.50** gain (a 50-point
jump; 5 of 10 tasks needed a second attempt and all 5 then passed). Agent answer
quality is corroborated separately: citation relevance **93%** (25/27 cited
chunks relevant, all 6 tasks cite), and 3/3 broken snippets fixed clean
(non-zero → zero exit). Evidence: `agent_eval.json`, `agent_quality.json`.

**Evals double as automated gates.** The same scripts run in CI and **exit
non-zero when a metric falls below threshold** (e.g. the production-parity gate
of 0.9), so a regression in faithfulness, coverage, or agent self-correction
fails the build rather than shipping silently.

## Known Limitations

- **Golden-dataset bias:** reference contexts are bootstrapped from T1b/T3, so
  those systems have a structural edge on reference-*based* metrics. W2 is the
  only blind system. The `expected_file_hit` / `expected_source_recall` checks
  use independent test-question metadata and are immune to this — which is why
  they are reported alongside the reference-based metrics.
- **Metric saturation:** with strong systems and a 0.5 threshold, reference-based
  scores cluster at 0.94–1.0; real separation shows up in answer-coverage, nDCG,
  and the ground-truth attribution check, not in precision/recall.
- **12 questions is small** — only four exercise code-file retrieval, so the
  headline T3-vs-T1b file-hit gap rests on four data points.
- **Single reference answer per question:** a paraphrase a human would accept can
  score "unsupported" under the deterministic threshold; this is why the
  paraphrase-tolerant LLM judges are triangulated *against* the deterministic
  method rather than replaced by it.
