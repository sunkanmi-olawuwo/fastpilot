"""Human-in-the-loop verification of the agent's self-verification (Phase 4, plan §7).

The agent self-tests with its OWN TestClient assertions (D7) — but only for the cases
it thought of. This probes 3 *passed* agent solutions (captured in
``evaluations/eval_results/agent_code/``) with edge cases the agent did NOT assert —
wrong types, missing fields, boundaries — by appending a probe to the real generated
code and running it through the same sandbox the Playground uses (``get_executor``).

The probe expectations are hand-written (the "human" in human-in-the-loop): each encodes
what *correct* behaviour should be; ``ok`` means the agent's code matched it. Honest
either way — a held probe is robustness (often FastAPI/Pydantic's framework guarantees
surfacing through the agent's thin self-test); a broken one is a logged limitation.

Usage (from repo root):
    uv run python final-submission/scripts/09_human_verification_probes.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import _bootstrap  # noqa: F401  (sys.path + trust store)

from app.augmentations.code_executor import get_executor

_SUB = Path(__file__).resolve().parent.parent
CODE_DIR = _SUB / "evaluations" / "eval_results" / "agent_code"
OUT = _SUB / "evaluations" / "eval_results" / "human_verification.json"

# Each probe: a request that sets `_r`, and an `expect` over `_r` / `_body` describing
# the behaviour the agent's own asserts never checked.
PROBES: dict[str, list[dict]] = {
    "pydantic_validation": [
        {
            "desc": "wrong type: age='abc'",
            "req": "_r = _pc.post('/users/', json={'name':'X','age':'abc'})",
            "expect": "_r.status_code == 422",
            "want": "422",
        },
        {
            "desc": "missing required field 'name'",
            "req": "_r = _pc.post('/users/', json={'age':30})",
            "expect": "_r.status_code == 422",
            "want": "422",
        },
        {
            "desc": "lower boundary age=1 (gt=0) is valid",
            "req": "_r = _pc.post('/users/', json={'name':'X','age':1})",
            "expect": "_r.status_code == 200",
            "want": "200",
        },
        {
            "desc": "unknown extra field is ignored, not echoed",
            "req": "_r = _pc.post('/users/', json={'name':'X','age':30,'role':'admin'})",
            "expect": "_r.status_code == 200 and 'role' not in _body",
            "want": "200 & no 'role'",
        },
    ],
    "response_model": [
        {
            "desc": "password stripped on a minimal body (no full_name)",
            "req": "_r = _pc.post('/users/', json={'username':'u2','password':'p2','email':'a@b.c'})",
            "expect": "_r.status_code == 200 and 'password' not in _body",
            "want": "200 & no password",
        },
        {
            "desc": "missing required 'email'",
            "req": "_r = _pc.post('/users/', json={'username':'u','password':'p'})",
            "expect": "_r.status_code == 422",
            "want": "422",
        },
        {
            "desc": "client-injected extra field not leaked by response_model",
            "req": "_r = _pc.post('/users/', json={'username':'u','password':'p','email':'a@b.c','is_admin':True})",
            "expect": "_r.status_code == 200 and 'is_admin' not in _body and 'password' not in _body",
            "want": "200 & whitelist only",
        },
    ],
    "depends": [
        {
            "desc": "wrong type on the OTHER param: limit='abc'",
            "req": "_r = _pc.get('/items/?limit=abc')",
            "expect": "_r.status_code == 422",
            "want": "422",
        },
        {
            "desc": "no lower bound: skip=-5 is accepted (honest: agent set no constraint)",
            "req": "_r = _pc.get('/items/?skip=-5')",
            "expect": "_r.status_code == 200 and _body == {'skip':-5,'limit':10}",
            "want": "200 {skip:-5,limit:10}",
        },
        {
            "desc": "float rejected: skip=1.5",
            "req": "_r = _pc.get('/items/?skip=1.5')",
            "expect": "_r.status_code == 422",
            "want": "422",
        },
    ],
}

_HARNESS = """

# === human-verification probe (appended; not part of the agent's code) ===
import json as _json
from fastapi.testclient import TestClient as _TC
_pc = _TC(app)
{req}
try:
    _body = _r.json()
except Exception:
    _body = None
_ok = bool({expect})
print("PROBE_RESULT " + _json.dumps({{"status": _r.status_code, "ok": _ok, "body": _body}}))
"""


def _run_probe(code: str, probe: dict) -> dict:
    program = code + _HARNESS.format(req=probe["req"], expect=probe["expect"])
    result = get_executor().run(program)
    line = next((ln for ln in result.stdout.splitlines() if ln.startswith("PROBE_RESULT ")), None)
    if line is None:  # agent's own asserts crashed, or sandbox error — inconclusive
        return {
            "ok": None,
            "status": None,
            "body": None,
            "harness_exit": result.exit_code,
            "stderr": (result.stderr or "")[-200:],
        }
    data = json.loads(line[len("PROBE_RESULT ") :])
    return {"ok": data["ok"], "status": data["status"], "body": data["body"]}


def main() -> int:
    report = {}
    total = held = 0
    for task, probes in PROBES.items():
        code = (CODE_DIR / f"{task}.py").read_text()
        rows = []
        print(f"\n{task}:")
        for p in probes:
            r = _run_probe(code, p)
            total += 1
            mark = "ok " if r["ok"] else ("FAIL" if r["ok"] is False else "??? ")
            held += int(r["ok"] is True)
            print(f"  [{mark}] {p['desc']:<52} want={p['want']:<22} got={r['status']}")
            rows.append({**{"desc": p["desc"], "want": p["want"]}, **r})
        report[task] = rows

    OUT.write_text(json.dumps(report, indent=2))
    print("\n" + "=" * 64)
    print(f"  probes held: {held}/{total}  (a held probe = the agent's endpoint did the sensible thing)")
    print("=" * 64)
    # This is observational, not a gate — we report honestly, pass or fail.
    return 0


if __name__ == "__main__":
    sys.exit(main())
