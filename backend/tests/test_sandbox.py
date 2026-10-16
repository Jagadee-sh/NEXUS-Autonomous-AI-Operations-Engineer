"""Python sandbox security tests."""

from __future__ import annotations

import pytest

from nexus.core.exceptions import SecurityError
from nexus.execution.sandbox import run_python_sandbox, validate_code


def test_simple_execution():
    r = run_python_sandbox("result = 2 + 2\nsummary = {'ok': True}\n")
    assert r.ok and r.result == 4


def test_pandas_with_dataset(tmp_path):
    import pandas as pd

    csv = tmp_path / "d.csv"
    pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]}).to_csv(csv, index=False)
    r = run_python_sandbox("result = int(df['a'].sum())\n", str(csv))
    assert r.ok and r.result == 6


@pytest.mark.parametrize(
    "code",
    [
        "import os\nresult = os.getcwd()",
        "import subprocess\nresult = 1",
        "result = open('/etc/passwd').read()",
        "eval('1+1')",
        "exec('x=1')",
        "__import__('os')",
        "import socket\nresult = 1",
        "result = (lambda: __import__('os'))()",
    ],
)
def test_forbidden_code_rejected(code: str):
    with pytest.raises(SecurityError):
        validate_code(code)


def test_timeout_enforced():
    r = run_python_sandbox(
        "x = 0\nwhile True:\n    x += 1\n",
        timeout_seconds=2,
    )
    assert not r.ok and (r.timed_out or "timed out" in (r.error or "").lower())


def test_dunder_attribute_blocked():
    with pytest.raises(SecurityError):
        validate_code("result = (1).__class__")
