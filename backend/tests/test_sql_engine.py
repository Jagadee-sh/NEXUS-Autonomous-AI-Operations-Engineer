"""SQL engine safety tests."""

from __future__ import annotations

import pytest

from nexus.core.exceptions import SecurityError, ValidationError
from nexus.execution.sql_engine import execute_readonly_sql, validate_sql


def test_select_allowed():
    assert validate_sql("SELECT 1").startswith("SELECT")


def test_cte_allowed():
    sql = "WITH t AS (SELECT 1 AS x) SELECT * FROM t"
    assert validate_sql(sql)


@pytest.mark.parametrize(
    "bad",
    [
        "DROP TABLE users",
        "DELETE FROM users",
        "UPDATE users SET a=1",
        "INSERT INTO users VALUES (1)",
        "ALTER TABLE users ADD c INT",
        "TRUNCATE TABLE users",
        "CREATE TABLE x (a INT)",
        "SELECT 1; DROP TABLE users",
        "ATTACH DATABASE 'evil.db' AS evil",
        "PRAGMA table_info(users)",
    ],
)
def test_mutations_rejected(bad: str):
    with pytest.raises((SecurityError, ValidationError)):
        validate_sql(bad)


def test_table_allowlist_enforced():
    with pytest.raises(ValidationError):
        validate_sql("SELECT * FROM secret_table", allowed_tables=["sales"])


async def test_execute_sqlite_readonly(tmp_path):
    import sqlite3

    db = tmp_path / "d.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE sales (id INTEGER, amount REAL)")
    conn.execute("INSERT INTO sales VALUES (1, 100.0), (2, 200.0)")
    conn.commit()
    conn.close()
    url = f"sqlite+aiosqlite:///{db}"

    ok = await execute_readonly_sql("SELECT SUM(amount) AS total FROM sales", url)
    assert ok.ok and ok.rows[0][0] == 300.0

    bad = await execute_readonly_sql("DELETE FROM sales", url)
    assert not bad.ok
    assert "SELECT" in (bad.error or "") or "select" in (bad.error or "").lower()
