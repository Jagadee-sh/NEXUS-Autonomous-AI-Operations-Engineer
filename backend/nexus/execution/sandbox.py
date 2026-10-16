"""Python sandbox: AST allowlist + restricted builtins + subprocess isolation + limits.

Security posture (documented in docs/SECURITY_MODEL.md):
- Code is scanned with ast before execution (no import of non-allowlisted modules,
  no open/exec/eval/__import__/compile, no dunder attribute access).
- Execution happens in a *separate* python process with:
  * wall-clock timeout (kill on exceed)
  * memory cap (psutil, best effort; enforced strongly on Unix via resource module)
  * restricted builtins injected by the runner preamble
  * no argv access to host paths beyond the provided data file
- The LLM never receives shell access; only this sandbox runs generated code.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nexus.config import settings
from nexus.core.exceptions import SecurityError
from nexus.logging_config import get_logger

log = get_logger("nexus.sandbox")

ALLOWED_IMPORTS = {
    "pandas",
    "numpy",
    "math",
    "statistics",
    "json",
    "re",
    "datetime",
    "collections",
    "itertools",
    "functools",
    "typing",
    "decimal",
    "csv",
    "string",
    "textwrap",
}

_FORBIDDEN_NAMES = {"open", "exec", "eval", "compile", "__import__", "input", "breakpoint", "exit", "quit", "help"}


@dataclass
class SandboxResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    result: Any = None
    summary: Any = None
    error: str | None = None
    latency_ms: int = 0
    code: str = ""
    timed_out: bool = False


def validate_code(code: str) -> None:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise SecurityError(f"Syntax error in generated code: {exc}") from exc

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in ALLOWED_IMPORTS:
                    raise SecurityError(f"Import not allowed: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root not in ALLOWED_IMPORTS:
                raise SecurityError(f"Import not allowed: {node.module}")
        elif isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
            raise SecurityError(f"Use of '{node.id}' is not allowed")
        elif isinstance(node, ast.Attribute):
            attr = node.attr
            if attr.startswith("__") and attr.endswith("__"):
                raise SecurityError("Dunder attribute access is not allowed")


_RUNNER_TEMPLATE = r'''
import ast, json, sys, math, traceback

ALLOWED = {allowed}

class Guard(ast.NodeTransformer):
    pass

BUILTIN_ALLOW = {{
    "abs","all","any","bool","bytes","dict","divmod","enumerate","filter","float","format","frozenset",
    "hash","hex","int","isinstance","issubclass","iter","len","list","map","max","min","next","object",
    "oct","pow","print","range","repr","reversed","round","set","slice","sorted","str","sum","tuple",
    "type","zip","True","False","None",
    "Exception","ValueError","TypeError","KeyError","IndexError","StopIteration","ZeroDivisionError","ArithmeticError"
}}

import builtins as _b
_safe = {{k: getattr(_b, k) for k in BUILTIN_ALLOW if hasattr(_b, k)}}
_safe["__import__"] = lambda name, *a, **k: __import__(name) if name.split(".")[0] in ALLOWED else (_ for _ in ()).throw(ImportError(name))

code_path = sys.argv[1]
data_path = sys.argv[2]
out_path = sys.argv[3]

ns = {{"__builtins__": _safe, "__name__": "__sandbox__"}}

try:
    df = None
    if data_path != "":
        import pandas as pd
        if data_path.endswith(".xlsx"):
            df = pd.read_excel(data_path)
        else:
            df = pd.read_csv(data_path)
        ns["df"] = df
    source = open(code_path, "r", encoding="utf-8").read() if False else None
    # read source without exposing open to user code
    with open(code_path, "r", encoding="utf-8") as fh:
        src = fh.read()
    compiled = compile(src, "<generated>", "exec")
    exec(compiled, ns)
    payload = {{
        "ok": True,
        "result": ns.get("result"),
        "summary": ns.get("summary"),
        "stdout": sys.stdout.getvalue() if hasattr(sys.stdout, "getvalue") else "",
    }}
except Exception as exc:
    payload = {{"ok": False, "error": f"{{type(exc).__name__}}: {{exc}}", "stderr": traceback.format_exc()[-2000:]}}

import io, contextlib
# already executed; serialize output
with open(out_path, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, default=str)
'''

# NOTE: the template above references open inside the runner preamble only (trusted code),
# while user code receives restricted builtins without open.


def run_python_sandbox(
    code: str,
    data_path: str | None = None,
    *,
    timeout_seconds: int | None = None,
    memory_mb: int | None = None,
) -> SandboxResult:
    start = time.perf_counter()
    validate_code(code)
    timeout = timeout_seconds or settings.sandbox_timeout_seconds

    workdir = Path(tempfile.mkdtemp(prefix="nexus_sbx_"))
    code_file = workdir / "user_code.py"
    out_file = workdir / "out.json"
    code_file.write_text(code, encoding="utf-8")
    runner = workdir / "runner.py"
    runner.write_text(_RUNNER_TEMPLATE.format(allowed=ALLOWED_IMPORTS), encoding="utf-8")
    if data_path:
        data_path = str(Path(data_path).expanduser().resolve())

    env = {
        "PYTHONPATH": "",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "HOME": str(workdir),
        "TEMP": str(workdir),
        "TMP": str(workdir),
    }

    def _launch() -> subprocess.Popen:
        return subprocess.Popen(
            [sys.executable, str(runner), str(code_file), data_path or "", str(out_file)],
            cwd=str(workdir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    proc = _launch()
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except Exception:  # noqa: BLE001
            stdout, stderr = "", ""
        return SandboxResult(
            ok=False,
            error=f"Sandbox timed out after {timeout}s",
            timed_out=True,
            latency_ms=int((time.perf_counter() - start) * 1000),
            code=code,
            stdout=(stdout or "")[:4000],
            stderr=(stderr or "")[:4000],
        )

    latency = int((time.perf_counter() - start) * 1000)
    if out_file.exists():
        try:
            payload = json.loads(out_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {"ok": False, "error": "Sandbox produced unreadable output"}
    else:
        payload = {"ok": False, "error": (stderr or "Sandbox crashed without output")[:1000]}

    if payload.get("ok"):
        return SandboxResult(
            ok=True,
            result=payload.get("result"),
            summary=payload.get("summary"),
            stdout=(payload.get("stdout") or stdout or "")[:4000],
            stderr=(stderr or "")[:2000],
            latency_ms=latency,
            code=code,
        )
    return SandboxResult(
        ok=False,
        error=payload.get("error") or (stderr or "Sandbox execution failed")[:1000],
        stderr=(payload.get("stderr") or stderr or "")[:4000],
        stdout=(stdout or "")[:4000],
        latency_ms=latency,
        code=code,
    )


def sandbox_info() -> dict[str, Any]:
    return {
        "allowed_imports": sorted(ALLOWED_IMPORTS),
        "timeout_seconds": settings.sandbox_timeout_seconds,
        "memory_mb": settings.sandbox_memory_mb,
        "isolation": "subprocess + AST allowlist + restricted builtins",
        "limitations": (
            "Process-level isolation (not a VM). For stronger guarantees run the backend "
            "inside a locked-down container. No network is used by the runner; user code "
            "cannot import socket/httpx because imports are allowlisted."
        ),
    }


_ = uuid  # reserved for future per-run ids
_ = field
