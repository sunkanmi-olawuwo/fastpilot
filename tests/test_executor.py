"""Sandbox executor safety suite (AC3.3) — the highest-value tests in the repo.

These run *real* subprocesses (no network, no creds). Small limits keep them fast.
The memory-limit case only enforces reliably on Linux (RLIMIT_AS), so it's skipped
elsewhere.
"""

from __future__ import annotations

import sys

import pytest
from app.augmentations.code_executor import SubprocessExecutor, scan_code

# Fast limits so the timeout case doesn't take 15s.
EXEC = SubprocessExecutor(wall_timeout_s=4, cpu_seconds=3, mem_mb=256)

HAPPY = """
from fastapi import FastAPI
from fastapi.testclient import TestClient

app = FastAPI()

@app.get("/ping")
def ping():
    return {"pong": True}

client = TestClient(app)
r = client.get("/ping")
print("status", r.status_code, r.json())
assert r.status_code == 200
"""


def test_happy_path_testclient():
    result = EXEC.run(HAPPY)
    assert result.ok, result.stderr
    assert "status 200" in result.stdout
    assert result.exit_code == 0


def test_stderr_and_nonzero_exit_captured():
    result = EXEC.run("import sys\nprint('to err', file=sys.stderr)\nraise ValueError('boom')\n")
    assert not result.ok
    assert result.exit_code != 0
    assert "boom" in result.stderr
    assert "to err" in result.stderr


def test_infinite_loop_killed():
    result = EXEC.run("while True:\n    pass\n")
    assert not result.ok
    assert result.duration_ms <= 16_000  # killed by CPU/wall limit, not hung


def test_network_blocked_at_runtime():
    # urllib is an allowed import; the runtime socket guard must still block the connect.
    code = "import urllib.request\nurllib.request.urlopen('http://example.com', timeout=3)\n"
    result = EXEC.run(code)
    assert not result.ok
    assert "disabled" in result.stderr or "OSError" in result.stderr or "URLError" in result.stderr


@pytest.mark.parametrize(
    "code,needle",
    [
        ("import subprocess\nsubprocess.run(['ls'])\n", "subprocess"),
        ("import os\nos.system('echo hi')\n", "os.system"),
        ("eval('1+1')\n", "eval"),
        # Reflection escapes: reach denied objects without naming them. All blocked at scan.
        ("print(().__class__.__bases__[0].__subclasses__())\n", "__subclasses__"),
        ("getattr((), '__cl' + 'ass__')\n", "getattr"),
        ("print(globals())\n", "globals"),
        ("print(open('/etc/passwd').read())\n", "open"),
    ],
)
def test_denylist_rejects_before_execution(code, needle):
    result = EXEC.run(code)
    assert result.blocked is True
    assert needle in (result.block_reason or "")
    assert result.duration_ms == 0  # never ran


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="RLIMIT_AS enforced on Linux")
def test_memory_limit_enforced():
    result = EXEC.run("x = bytearray(2 * 1024 * 1024 * 1024)\nprint('allocated')\n")
    assert not result.ok
    assert "allocated" not in result.stdout


def test_temp_dir_isolation_no_leak():
    # The file the agent writes lives in the throwaway temp cwd; nothing persists.
    code = "from pathlib import Path\nPath('scratch.txt').write_text('x')\nprint(Path.cwd())\n"
    result = EXEC.run(code)
    assert result.ok
    assert "fastpilot_sbx_" in result.stdout  # ran inside an isolated temp dir


# --- scan_code units (no subprocess) --------------------------------------
def test_scan_allows_normal_fastapi():
    ok, reason = scan_code(HAPPY)
    assert ok and reason is None


def test_scan_allows_syntax_error_through():
    ok, _ = scan_code("def f(:\n  pass")  # let the sandbox surface the traceback
    assert ok


def test_scan_rejects_import_from_denied_module():
    ok, reason = scan_code("from subprocess import run\nrun(['ls'])\n")
    assert ok is False
    assert "subprocess" in reason


def test_scan_rejects_os_exec_family():
    ok, reason = scan_code("import os\nos.execv('/bin/sh', ['sh'])\n")
    assert ok is False
    assert "os.exec" in reason


# --- runtime limits + output handling -------------------------------------
def test_wall_timeout_kills_sleeping_process():
    # time.sleep burns no CPU, so only the wall-clock timer can stop it.
    fast = SubprocessExecutor(wall_timeout_s=1, cpu_seconds=3, mem_mb=256)
    result = fast.run("import time\ntime.sleep(30)\nprint('done')\n")
    assert result.timed_out is True
    assert not result.ok
    assert result.exit_code == -9
    assert "wall-clock timeout" in result.stderr
    assert "done" not in result.stdout


def test_stdout_truncated_to_max_output():
    small = SubprocessExecutor(wall_timeout_s=4, cpu_seconds=3, mem_mb=256, max_output_chars=10)
    result = small.run("print('x' * 1000)\n")
    assert len(result.stdout) <= 10  # capped, never floods the UI/transcript
