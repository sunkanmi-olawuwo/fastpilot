"""Agent mode evaluation (Phase 4 gate) — measures the augmentation's value.

Runs each golden task in ``evaluations/agent_tasks.json`` through the real agent
orchestrator in-process and reports:
  - success rate WITH self-correction (the agent's final verdict)
  - success rate WITHOUT it (whether attempt 1 already passed)
The ON−OFF delta *is* the self-correction augmentation result (augmentation-decisions.md).

Needs live creds (Gemini/Qdrant/Voyage). Exits non-zero if the with-correction success
rate is below the 0.80 gate. Writes a slim JSON to evaluations/eval_results/.

Usage (from repo root):
    uv run python final-submission/scripts/06_run_agent_eval.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import _bootstrap  # noqa: F401

from app.augmentations.agent_orchestrator import AgentOrchestrator
from app.augmentations.code_executor import get_executor
from app.services import get_rag_pipeline

_SUBMISSION = Path(__file__).resolve().parent.parent
TASKS = _SUBMISSION / "evaluations" / "agent_tasks.json"
OUT_DIR = _SUBMISSION / "evaluations" / "eval_results"
GATE = 0.80


async def _run_task(task: str) -> dict:
    orch = AgentOrchestrator(pipeline=get_rag_pipeline(), executor=get_executor())
    first_exit: int | None = None
    success = False
    attempts = 0
    async for ev in orch.run(task):
        if ev["event"] == "exec_result" and first_exit is None:
            first_exit = ev["data"]["exit_code"]
        elif ev["event"] == "done":
            success = bool(ev["data"].get("success"))
            attempts = int(ev["data"].get("attempts", 0))
    return {"first_attempt_ok": first_exit == 0, "success": success, "attempts": attempts}


def main() -> int:
    tasks = json.loads(TASKS.read_text())
    results = []
    for t in tasks:
        r = asyncio.run(_run_task(t["task"]))
        results.append({"id": t["id"], "concept": t["concept"], **r})
        flag = "PASS" if r["success"] else "FAIL"
        print(f"  {flag}  {t['id']:<20} attempts={r['attempts']} first_try={r['first_attempt_ok']}")

    n = len(results)
    on = sum(r["success"] for r in results) / n
    off = sum(r["first_attempt_ok"] for r in results) / n
    summary = {
        "n": n,
        "success_with_correction": round(on, 3),
        "success_first_attempt_only": round(off, 3),
        "self_correction_delta": round(on - off, 3),
        "results": results,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "agent_eval.json").write_text(json.dumps(summary, indent=2))

    print("\n" + "=" * 60)
    print(f"  with self-correction : {on:.0%}")
    print(f"  first attempt only   : {off:.0%}")
    print(f"  self-correction gain : {on - off:+.0%}  (this is the augmentation result)")
    print("=" * 60)
    if on < GATE:
        print(f"  FAIL — below the {GATE:.0%} gate.")
        return 1
    print("  PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
