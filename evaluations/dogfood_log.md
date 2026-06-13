# Dogfood Log

> Real-usage learning log (plan §11.2). The backend auto-appends raw exchanges to
> `dogfood/sessions.jsonl` at the **repo root** (gitingest-invisible); this file is the
> curated distillation, produced by "harvest the dogfood log".

## Harvest — Phase 1–4 (2026-06-11 → 06-12)
23 interactions + 2 feedback events logged to `dogfood/sessions.jsonl`. The most
instructive real-usage exchanges (the rest are Phase-4 parity-eval golden traffic):

| Date | Question | Mode | Quality (1–5) | Note |
|------|----------|------|---------------|------|
| 06-11 | How do I declare a path parameter with a type? | chat | 5 | Substantive (1.8k chars), cited; the **repeat ask hit the semantic cache** (`cache_hit=True`, same answer) — cache validated in real use. |
| 06-11 | how do I make it optional? | chat | 5 | **Follow-up rewrite worked**: resolved "it" → "How do I make a path parameter optional in FastAPI?" |
| 06-11 | can it be an integer? | chat | 4 | Follow-up rewrite resolved "it" → "Can a query parameter with a default value be an integer?" — correct referent across a topic shift. |
| 06-11 | How do I use Pydantic models for request bodies? | chat | 5 | 4.5k chars; repeat hit the cache. |
| 06-11 | How do I declare a query parameter with a default value? | chat | 5 | Repeat hit the cache. |
| 06-11 | How do I return a custom status code? | chat | 5 | 5k chars, thorough. |
| 06-12 | (12 golden questions, Phase-4 parity eval) | chat | — | Scored live: see `eval_results/production_parity.json`. |

**Feedback:** 2 thumbs-up recorded (`msg_c9dc9c9f…`, `msg_053c4a8c…`), 0 thumbs-down.

## Findings
- **The mechanism works end-to-end** — exchanges auto-append to the repo-root JSONL
  (gitingest-invisible), feedback joins by `msg_id`, and this harvest distils them.
- **Conditional rewrite + cache both validated in real traffic**, not just in tests: the
  path-parameter follow-up chain shows "it"/"can it" resolved correctly across turns, and
  repeated questions served from the semantic cache (`cache_hit=True`, identical answer).
- **No weak-answer outliers surfaced** in the logged sessions — answers were substantial
  (1.7k–5k chars) and cited; the golden-question traffic scored at/above the gate
  (`production_parity.json`). So there were no 3–5 clearly-weak answers to *promote* to new
  eval questions this round.
- **Honest gap:** these sessions are predominantly dev + eval traffic, not sustained human
  dogfooding. Deeper interactive use against the **deployed URL** (flagging genuinely weak
  answers in the wild) is a Phase-5 activity; the logging + harvest path is proven and ready
  to capture it.
