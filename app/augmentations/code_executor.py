"""Sandboxed code executor (D6) — the one net-new piece with no class equivalent.

Runs agent-generated / user FastAPI code with layered defenses:
  1. AST pre-scan denylist  — reject obvious escapes before anything runs.
  2. Subprocess isolation   — fresh temp dir as cwd, ``python -I`` (isolated), scrubbed
                              env (no API keys), own process group.
  3. resource limits        — RLIMIT_CPU / RLIMIT_AS / RLIMIT_FSIZE via preexec_fn.
  4. wall-clock timeout      — killpg the whole group on overrun.
  5. network guard          — a prelude monkeypatches ``socket.connect`` to raise, so
                              urllib/requests/httpx all fail at connect (TestClient is
                              in-process ASGI, so it's unaffected).

Residual risk is honest: this is a course demo on a single box, not a multi-tenant
sandbox — full FS reads are still possible. A Docker backend (``--network none
--memory 256m``) is the documented production-grade alternative.

The generated code self-verifies in-process with ``fastapi.testclient.TestClient`` (D7),
so "running" never binds a port and stdout is a clean request/response log.
"""

from __future__ import annotations

import ast
import logging
import os
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# --- AST denylist ---------------------------------------------------------
_DENIED_IMPORTS = {
    "subprocess",
    "socket",
    "_socket",
    "ctypes",
    "multiprocessing",
    "resource",
    "mmap",
    "fcntl",
    "pty",
    "shutil",
}
_DENIED_CALL_PATHS = {
    "os.system",
    "os.popen",
    "os.remove",
    "os.unlink",
    "os.rmdir",
    "os.removedirs",
    "os.kill",
    "os.fork",
    "os.setuid",
    "os.setgid",
    "shutil.rmtree",
    "shutil.move",
    "importlib.import_module",
}
_DENIED_BUILTINS = {"eval", "exec", "__import__", "compile"}

_NET_PRELUDE = (
    "import socket as _fp_sock\n"
    "def _fp_no_net(*a, **k):\n"
    "    raise OSError('network access is disabled in the FastPilot sandbox')\n"
    "_fp_sock.socket.connect = _fp_no_net\n"
    "_fp_sock.socket.connect_ex = _fp_no_net\n"
)


def _dotted(node: ast.AST) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def scan_code(code: str) -> tuple[bool, str | None]:
    """Static pre-scan. Returns (ok, reason). A SyntaxError is *allowed* through so the
    sandbox runs it and the agent gets a clean traceback to fix."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return True, None
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in _DENIED_IMPORTS:
                    return False, f"import of '{alias.name}' is not allowed in the sandbox"
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in _DENIED_IMPORTS:
                return False, f"import from '{node.module}' is not allowed in the sandbox"
        elif isinstance(node, ast.Call):
            name = _dotted(node.func)
            if name and (name in _DENIED_CALL_PATHS or (name.startswith("os.exec"))):
                return False, f"call to '{name}' is not allowed in the sandbox"
            if isinstance(node.func, ast.Name) and node.func.id in _DENIED_BUILTINS:
                return False, f"use of '{node.func.id}' is not allowed in the sandbox"
    return True, None


# --- Result ---------------------------------------------------------------
@dataclass
class ExecutionResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    blocked: bool = False
    block_reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and not self.blocked


def _is_secret_key(key: str) -> bool:
    upper = key.upper()
    return any(tok in upper for tok in ("KEY", "TOKEN", "SECRET", "PASSWORD", "QDRANT", "REDIS", "OPIK"))


def _scrubbed_env() -> dict[str, str]:
    """Pass through a minimal env with all credential-shaped vars removed."""
    return {k: v for k, v in os.environ.items() if not _is_secret_key(k)}


def _preexec(cpu_s: int, mem_bytes: int, fsize_bytes: int):  # noqa: ANN202
    def _apply() -> None:
        import resource

        os.setsid()  # own process group so a timeout can killpg the whole tree
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 1))
        for limit, value in ((resource.RLIMIT_AS, mem_bytes), (resource.RLIMIT_FSIZE, fsize_bytes)):
            try:
                resource.setrlimit(limit, (value, value))
            except (ValueError, OSError):  # not all limits enforce on every OS (macOS RLIMIT_AS)
                pass

    return _apply


class SubprocessExecutor:
    """Default executor (D6). Construct with small limits in tests for speed."""

    def __init__(
        self,
        *,
        wall_timeout_s: int = 15,
        cpu_seconds: int = 10,
        mem_mb: int = 512,
        max_output_chars: int = 20_000,
        max_file_bytes: int = 5_000_000,
    ):
        self.wall_timeout_s = wall_timeout_s
        self.cpu_seconds = cpu_seconds
        self.mem_bytes = mem_mb * 1024 * 1024
        self.max_output = max_output_chars
        self.max_file_bytes = max_file_bytes

    def run(self, code: str) -> ExecutionResult:
        ok, reason = scan_code(code)
        if not ok:
            logger.info("Sandbox blocked code: %s", reason)
            return ExecutionResult(-1, "", reason or "blocked", 0, blocked=True, block_reason=reason)

        with tempfile.TemporaryDirectory(prefix="fastpilot_sbx_") as tmp:
            (Path(tmp) / "main.py").write_text(_NET_PRELUDE + "\n" + code, encoding="utf-8")
            start = time.monotonic()
            proc = subprocess.Popen(
                [sys.executable, "-I", "main.py"],
                cwd=tmp,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=_scrubbed_env(),
                preexec_fn=_preexec(self.cpu_seconds, self.mem_bytes, self.max_file_bytes),
            )
            timed_out = False
            try:
                stdout, stderr = proc.communicate(timeout=self.wall_timeout_s)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
                stdout, stderr = proc.communicate()
            duration_ms = int((time.monotonic() - start) * 1000)

            return ExecutionResult(
                exit_code=-9 if timed_out else (proc.returncode or 0),
                stdout=(stdout or "")[: self.max_output],
                stderr=((stderr or "") if not timed_out else (stderr or "") + "\n[sandbox] killed: wall-clock timeout")[
                    : self.max_output
                ],
                duration_ms=duration_ms,
                timed_out=timed_out,
            )


_executor: SubprocessExecutor | None = None


def get_executor() -> SubprocessExecutor:
    """Singleton executor built from settings (wall/cpu/mem from config)."""
    global _executor
    if _executor is None:
        from app.config import get_settings

        s = get_settings()
        _executor = SubprocessExecutor(
            wall_timeout_s=s.executor_wall_timeout_s,
            cpu_seconds=s.executor_cpu_seconds,
            mem_mb=s.executor_mem_mb,
        )
    return _executor
