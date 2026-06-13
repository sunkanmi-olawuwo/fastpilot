"""Agent-mode quality gates AC3.4 + AC3.9 (Phase 4) — live, through the real pipeline.

AC3.4 (citation spot-check): for a spread of golden tasks, the agent's final code must
carry [n] citations, and >=80% of the *cited* context chunks must actually mention a
FastAPI/Pydantic API that the generated code uses (a cited source the code didn't draw
on is a dangling citation). We compute, per task, the set of FastAPI/Pydantic API tokens
present in the generated code, then check each cited chunk's text mentions at least one
of them (or the task concept) — i.e. the citation points at a chunk about the API used.

AC3.9 (Fix-with-AI): three seeded broken snippets — a syntax error, a missing import, and
a failing assertion — each get ONE fix round through the same /fix path (AGENT_FIX_PROMPT
-> Gemini -> extract_code), then run in the sandbox. >=2/3 must come back clean (exit 0).
(The /fix rate-limit coupling is covered separately in tests/test_agent_endpoints.py.)

Needs live creds. Writes evaluations/eval_results/agent_quality.json; exits non-zero if
either gate fails.

Usage (from repo root):
    uv run python final-submission/scripts/08_agent_quality_checks.py
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

import _bootstrap  # noqa: F401  (sys.path + trust store)

from app.augmentations.agent_orchestrator import AgentOrchestrator, extract_code
from app.augmentations.code_executor import get_executor
from app.prompts import AGENT_FIX_PROMPT
from app.services import get_rag_pipeline

_SUBMISSION = Path(__file__).resolve().parent.parent
TASKS = _SUBMISSION / "evaluations" / "agent_tasks.json"
OUT_DIR = _SUBMISSION / "evaluations" / "eval_results"

# Tasks sampled for the citation spot-check (a spread of concepts; spot-check, not exhaustive).
SPOTCHECK_IDS = ["path_param", "query_param", "pydantic_validation", "depends", "status_code", "response_model"]
CITATION_RELEVANCE_GATE = 0.80

# FastAPI / Pydantic API surface we recognise in generated code + cited chunks.
_API_TOKENS = [
    "FastAPI",
    "APIRouter",
    "Query",
    "Path",
    "Depends",
    "HTTPException",
    "status",
    "Header",
    "Cookie",
    "Form",
    "File",
    "UploadFile",
    "BackgroundTasks",
    "Response",
    "JSONResponse",
    "Request",
    "response_model",
    "BaseModel",
    "Field",
    "EmailStr",
    "status_code",
    "Body",
]
_CITATION_RE = re.compile(r"\[(\d+)\]")


# --- AC3.4 ----------------------------------------------------------------
async def _run_capturing(task: str) -> tuple[str, dict[int, str]]:
    """Run a task; return (final_code, {rank: chunk_content}) from the stream."""
    orch = AgentOrchestrator(pipeline=get_rag_pipeline(), executor=get_executor())
    contexts: dict[int, str] = {}
    code = ""
    async for ev in orch.run(task):
        if ev["event"] == "context":
            contexts[int(ev["data"]["rank"])] = ev["data"].get("content", "")
        elif ev["event"] == "code":
            code = ev["data"]["content"]  # keep the last (final) attempt
    return code, contexts


def _apis_used(code: str) -> set[str]:
    return {tok for tok in _API_TOKENS if re.search(rf"\b{re.escape(tok)}\b", code)}


def _chunk_is_relevant(chunk: str, used: set[str], concept: str) -> bool:
    low = chunk.lower()
    if any(tok.lower() in low for tok in used):
        return True
    return any(w in low for w in concept.lower().split() if len(w) > 3)  # concept fallback


async def citation_spotcheck() -> dict:
    tasks = {t["id"]: t for t in json.loads(TASKS.read_text())}
    per_task, cited_total, cited_relevant, tasks_with_citations = [], 0, 0, 0
    for tid in SPOTCHECK_IDS:
        t = tasks[tid]
        code, contexts = await _run_capturing(t["task"])
        used = _apis_used(code)
        cited_ranks = sorted({int(n) for n in _CITATION_RE.findall(code)})
        has_citations = bool(cited_ranks)
        tasks_with_citations += int(has_citations)
        relevant = 0
        for rank in cited_ranks:
            chunk = contexts.get(rank, "")  # missing rank = dangling citation = not relevant
            if chunk and _chunk_is_relevant(chunk, used, t["concept"]):
                relevant += 1
        cited_total += len(cited_ranks)
        cited_relevant += relevant
        per_task.append(
            {
                "id": tid,
                "has_citations": has_citations,
                "n_cited": len(cited_ranks),
                "n_relevant": relevant,
                "apis_used": sorted(used),
            }
        )
        print(f"  [3.4] {tid:<20} citations={len(cited_ranks)} relevant={relevant} apis={sorted(used)}")

    rel_rate = (cited_relevant / cited_total) if cited_total else 0.0
    all_cite = tasks_with_citations == len(SPOTCHECK_IDS)
    return {
        "n_tasks": len(SPOTCHECK_IDS),
        "tasks_with_citations": tasks_with_citations,
        "cited_chunks": cited_total,
        "cited_relevant": cited_relevant,
        "relevance_rate": round(rel_rate, 3),
        "all_tasks_cite": all_cite,
        "passed": all_cite and rel_rate >= CITATION_RELEVANCE_GATE,
        "per_task": per_task,
    }


# --- AC3.9 ----------------------------------------------------------------
_BROKEN = {
    "syntax_error": (
        "from fastapi import FastAPI\n"
        "from fastapi.testclient import TestClient\n"
        "app = FastAPI()\n"
        "@app.get('/ping')\n"
        "def ping(\n"  # unclosed paren -> SyntaxError
        "    return {'pong': True}\n"
        "client = TestClient(app)\n"
        "print(client.get('/ping').json())\n"
    ),
    "missing_import": (
        "from fastapi import FastAPI\n"
        "from fastapi.testclient import TestClient\n"
        "app = FastAPI()\n"
        "class Item(BaseModel):\n"  # BaseModel never imported -> NameError
        "    name: str\n"
        "@app.post('/items')\n"
        "def create(item: Item):\n"
        "    return item\n"
        "client = TestClient(app)\n"
        "print(client.post('/items', json={'name': 'x'}).status_code)\n"
    ),
    "failing_assertion": (
        "from fastapi import FastAPI\n"
        "from fastapi.testclient import TestClient\n"
        "app = FastAPI()\n"
        "@app.get('/n')\n"
        "def n():\n"
        "    return {'n': 1}\n"
        "client = TestClient(app)\n"
        "r = client.get('/n')\n"
        "print(r.json())\n"
        "assert r.json()['n'] == 2  # wrong expectation -> AssertionError\n"
    ),
}


async def _fix_once(code: str, stderr: str) -> str:
    """Mirror the /fix endpoint: one AGENT_FIX_PROMPT round, return the patched code."""
    from haystack.dataclasses import ChatMessage

    user = (
        f"TASK: fix this FastAPI code so it runs.\n\nPREVIOUS CODE:\n{code}\n\n"
        f"TRACEBACK / STDERR:\n{stderr}\n\nCONTEXT:\n(none — fix from the traceback)"
    )
    messages = [ChatMessage.from_system(AGENT_FIX_PROMPT), ChatMessage.from_user(user)]
    raw = await get_rag_pipeline().generate(user, [], messages)
    return extract_code(raw)


async def fix_eval() -> dict:
    executor = get_executor()
    per_snippet, clean = [], 0
    for name, broken in _BROKEN.items():
        before = executor.run(broken)
        assert not before.ok, f"{name} was supposed to be broken but ran clean"
        fixed_code = await _fix_once(broken, before.stderr or "(no stderr)")
        after = executor.run(fixed_code)
        ok = after.ok
        clean += int(ok)
        per_snippet.append(
            {"id": name, "before_exit": before.exit_code, "after_exit": after.exit_code, "fixed_clean": ok}
        )
        print(f"  [3.9] {name:<18} before_exit={before.exit_code} -> after_exit={after.exit_code} clean={ok}")
    return {"n": len(_BROKEN), "fixed_clean": clean, "passed": clean >= 2, "per_snippet": per_snippet}


def main() -> int:
    print("AC3.4 — citation spot-check:")
    cite = asyncio.run(citation_spotcheck())
    print("AC3.9 — Fix-with-AI on 3 broken snippets:")
    fix = asyncio.run(fix_eval())

    summary = {"ac3_4_citation": cite, "ac3_9_fix": fix}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "agent_quality.json").write_text(json.dumps(summary, indent=2))

    print("\n" + "=" * 60)
    print(
        f"  AC3.4 citations: {cite['cited_relevant']}/{cite['cited_chunks']} cited chunks relevant "
        f"({cite['relevance_rate']:.0%}); all tasks cite={cite['all_tasks_cite']} -> "
        f"{'PASS' if cite['passed'] else 'FAIL'}"
    )
    fix_verdict = "PASS" if fix["passed"] else "FAIL"
    print(f"  AC3.9 fix-with-AI: {fix['fixed_clean']}/{fix['n']} clean after one fix -> {fix_verdict}")
    print("=" * 60)
    ok = cite["passed"] and fix["passed"]
    print("  PASS" if ok else "  FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
