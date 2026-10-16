"""Read-only SQL engine with AST-level safety enforcement."""

from __future__ import annotations

import asyncio
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import sqlglot
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from nexus.config import settings
from nexus.core.exceptions import SecurityError, ValidationError
from nexus.logging_config import get_logger

log = get_logger("nexus.sql")

_FORBIDDEN_NODES = {
    "insert",
    "update",
    "delete",
    "drop",
    "create",
    "alter",
    "truncate",
    "grant",
    "attach",
    "detach",
    "pragma",
    "command",
    "merge",
}
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass
class SQLResult:
    ok: bool
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    error: str | None = None
    latency_ms: int = 0
    sql: str = ""


def validate_sql(sql: str, allowed_tables: list[str] | None = None) -> str:
    """Parse and enforce SELECT-only. Returns normalized SQL."""
    stripped = sql.strip().rstrip(";")
    if not stripped:
        raise ValidationError("Empty SQL")
    if ";" in stripped:
        raise SecurityError("Multiple SQL statements are not allowed")
    low = stripped.lower()
    for word in ("attach", "detach", "pragma", "load_extension"):
        if re.search(rf"\b{word}\b", low):
            raise SecurityError(f"Forbidden SQL keyword: {word}")

    try:
        expressions = sqlglot.parse(stripped, read="sqlite")
    except Exception as exc:  # noqa: BLE001
        raise ValidationError(f"SQL parse error: {exc}") from exc
    if not expressions or expressions[0] is None:
        raise ValidationError("Could not parse SQL")

    tree = expressions[0]
    root_kind = (tree.key or "").lower()
    if root_kind not in {"select", "union", "with"}:
        raise SecurityError(f"Only SELECT queries are allowed (got {root_kind.upper()})")

    for node in tree.walk():
        kind = (node.key or "").lower()
        if kind in _FORBIDDEN_NODES:
            raise SecurityError(f"Forbidden SQL construct: {kind.upper()}")

    if allowed_tables is not None:
        for table in tree.find_all(sqlglot.exp.Table):
            name = table.name
            if name and name.lower() not in {t.lower() for t in allowed_tables}:
                raise ValidationError(f"Table '{name}' is not in the allowed schema")
    return stripped


def _sqlite_tables(db_path: str) -> list[str]:
    if not Path(db_path).exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def discover_schema(connection_url: str) -> dict[str, list[str]]:
    """Return {table: [columns]} for sqlite or postgres URLs."""
    if connection_url.startswith("sqlite"):
        raw = connection_url.split("///", 1)[-1]
        path = raw
        if not Path(path).exists():
            return {}
        conn = sqlite3.connect(path)
        try:
            tables = [
                r[0]
                for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            ]
            schema: dict[str, list[str]] = {}
            for t in tables:
                if t.startswith("sqlite_"):
                    continue
                cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{t}")').fetchall()]
                schema[t] = cols
            return schema
        finally:
            conn.close()

    # postgres via sqlalchemy async — executed synchronously in thread by caller wrappers
    raise ValidationError("Async schema discovery required for postgres — use async_discover_schema")


async def async_discover_schema(connection_url: str) -> dict[str, list[str]]:
    if connection_url.startswith("sqlite"):
        return await asyncio.to_thread(discover_schema, connection_url)
    engine = create_async_engine(connection_url)
    try:
        async with engine.connect() as conn:
            if connection_url.startswith("postgres"):
                res = await conn.execute(
                    text(
                        "SELECT table_name, column_name FROM information_schema.columns "
                        "WHERE table_schema='public' ORDER BY table_name, ordinal_position"
                    )
                )
            else:
                raise ValidationError(f"Unsupported datasource kind: {connection_url.split(':')[0]}")
            schema: dict[str, list[str]] = {}
            for table, col in res.fetchall():
                schema.setdefault(table, []).append(col)
            return schema
    finally:
        await engine.dispose()


async def execute_readonly_sql(
    sql: str,
    connection_url: str,
    *,
    allowed_tables: list[str] | None = None,
    max_rows: int | None = None,
    timeout_seconds: int | None = None,
) -> SQLResult:
    import time

    start = time.perf_counter()
    try:
        normalized = validate_sql(sql, allowed_tables)
    except (SecurityError, ValidationError) as exc:
        return SQLResult(
            ok=False,
            error=exc.message,
            sql=sql.strip()[:500],
            latency_ms=int((time.perf_counter() - start) * 1000),
        )
    row_cap = max_rows or settings.sql_max_rows
    timeout = timeout_seconds or settings.sql_timeout_seconds

    if not connection_url.startswith("sqlite"):
        engine = create_async_engine(connection_url)

        async def _run() -> SQLResult:
            try:
                async with engine.connect() as conn:
                    res = await conn.execute(text(normalized))
                    rows_raw = res.fetchmany(row_cap + 1)
                    columns = list(res.keys()) if res.returns_rows else []
                    rows = [[_jsonable(v) for v in r] for r in rows_raw[:row_cap]]
                    truncated = len(rows_raw) > row_cap
                    return SQLResult(
                        ok=True,
                        columns=columns,
                        rows=rows,
                        row_count=len(rows),
                        truncated=truncated,
                        latency_ms=int((time.perf_counter() - start) * 1000),
                        sql=normalized,
                    )
            except SecurityError:
                raise
            except Exception as exc:  # noqa: BLE001
                return SQLResult(ok=False, error=str(exc)[:1000], sql=normalized, latency_ms=int((time.perf_counter() - start) * 1000))
            finally:
                await engine.dispose()

        return await asyncio.wait_for(_run(), timeout=timeout)

    # sqlite path
    raw = connection_url.split("///", 1)[-1]

    def _run_sync() -> SQLResult:
        conn = sqlite3.connect(raw, timeout=timeout)
        try:
            conn.execute("PRAGMA query_only = ON")
            cur = conn.execute(normalized)
            columns = [d[0] for d in cur.description] if cur.description else []
            rows_raw = cur.fetchmany(row_cap + 1)
            rows = [list(r) for r in rows_raw[:row_cap]]
            return SQLResult(
                ok=True,
                columns=columns,
                rows=rows,
                row_count=len(rows),
                truncated=len(rows_raw) > row_cap,
                latency_ms=int((time.perf_counter() - start) * 1000),
                sql=normalized,
            )
        except SecurityError:
            raise
        except Exception as exc:  # noqa: BLE001
            return SQLResult(
                ok=False,
                error=str(exc)[:1000],
                sql=normalized,
                latency_ms=int((time.perf_counter() - start) * 1000),
            )
        finally:
            conn.close()

    try:
        return await asyncio.wait_for(asyncio.to_thread(_run_sync), timeout=timeout + 2)
    except TimeoutError:
        return SQLResult(ok=False, error="SQL execution timed out", sql=normalized)


def _jsonable(v: Any) -> Any:
    if v is None or isinstance(v, (int, float, str, bool)):
        return v
    return str(v)


def sanitize_connection_url(url: str) -> str:
    """Basic sanity check; forbid non-sqlite/postgres schemes."""
    parsed = urlparse(url)
    if parsed.scheme not in {"sqlite", "postgresql", "postgres"}:
        raise ValidationError("Only sqlite:// and postgresql:// data sources are allowed")
    if parsed.scheme in {"postgresql", "postgres"} and not parsed.password:
        log.warning("postgres datasource without password in URL")
    return url


def safe_unquote(value: str) -> str:
    return unquote(value)
