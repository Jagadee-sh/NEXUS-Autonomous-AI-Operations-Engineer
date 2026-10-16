"""Tool abstraction, permissions, registry, and executor with audit."""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.config import settings
from nexus.core.exceptions import (
    ApprovalRequiredError,
    NotFoundError,
    PermissionDeniedError,
    SecurityError,
    ValidationError,
)
from nexus.database.base import utcnow
from nexus.database.models import ApprovalRequest, AuditLog, ToolExecution
from nexus.execution.sandbox import run_python_sandbox
from nexus.execution.sql_engine import async_discover_schema, execute_readonly_sql
from nexus.logging_config import get_logger
from nexus.retrieval.hybrid import RetrievalQuery, hybrid_retrieve

log = get_logger("nexus.tools")

RISK_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


@dataclass
class ToolContext:
    session: AsyncSession
    task_id: str | None = None
    agent: str = "tool_agent"
    user_role: str = "analyst"
    document_ids: list[str] | None = None
    dataset_paths: dict[str, str] = field(default_factory=dict)  # dataset_id -> path
    datasource_url: str | None = None


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    permission_level: str = "LOW"  # LOW|MEDIUM|HIGH|CRITICAL
    timeout_seconds: int = 30
    handler: Callable[[ToolContext, dict[str, Any]], Awaitable[Any]] | None = None


class Tool(ABC):
    spec: ToolSpec

    @abstractmethod
    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> Any: ...


def validate_args(schema: dict[str, Any], args: dict[str, Any]) -> None:
    props = schema.get("properties", {}) or {}
    required = schema.get("required", []) or []
    for r in required:
        if r not in args:
            raise ValidationError(f"Missing required argument: {r}")
    allowed = set(props)
    for key in args:
        if allowed and key not in allowed:
            raise ValidationError(f"Unknown argument: {key}")
    for key, spec in props.items():
        if key not in args:
            continue
        t = spec.get("type")
        v = args[key]
        if t == "string" and not isinstance(v, str):
            raise ValidationError(f"Argument {key} must be a string")
        if t == "integer" and not isinstance(v, int):
            raise ValidationError(f"Argument {key} must be an integer")
        if t == "number" and not isinstance(v, (int, float)):
            raise ValidationError(f"Argument {key} must be a number")
        if t == "array" and not isinstance(v, list):
            raise ValidationError(f"Argument {key} must be an array")
        if t == "object" and not isinstance(v, dict):
            raise ValidationError(f"Argument {key} must be an object")


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        if name not in self._tools:
            raise NotFoundError(f"Tool not found: {name}")
        return self._tools[name]

    def list(self) -> list[ToolSpec]:
        return list(self._tools.values())


registry = ToolRegistry()


# --------------------------------------------------------------------------- tools
async def _doc_search(ctx: ToolContext, args: dict[str, Any]) -> Any:
    hits = await hybrid_retrieve(
        ctx.session,
        RetrievalQuery(
            text=args["query"],
            top_k=int(args.get("top_k", 5)),
            document_ids=ctx.document_ids,
        ),
    )
    return {
        "results": [
            {
                "chunk_id": h.chunk_id,
                "document_id": h.document_id,
                "filename": h.filename,
                "page": h.page,
                "score": round(h.score, 4),
                "snippet": h.content[:500],
            }
            for h in hits
        ]
    }


async def _sql_query(ctx: ToolContext, args: dict[str, Any]) -> Any:
    if not ctx.datasource_url:
        raise ValidationError("No data source configured for this task")
    schema = await async_discover_schema(ctx.datasource_url)
    result = await execute_readonly_sql(args["sql"], ctx.datasource_url, allowed_tables=list(schema.keys()))
    if not result.ok:
        raise ValidationError(result.error or "SQL failed")
    return {
        "columns": result.columns,
        "rows": result.rows[:50],
        "row_count": result.row_count,
        "truncated": result.truncated,
        "latency_ms": result.latency_ms,
    }


async def _python_analysis(ctx: ToolContext, args: dict[str, Any]) -> Any:
    data_path = None
    dataset_id = args.get("dataset_id")
    if dataset_id:
        data_path = ctx.dataset_paths.get(dataset_id)
        if not data_path:
            raise ValidationError(f"Unknown dataset_id: {dataset_id}")
    result = run_python_sandbox(args["code"], data_path)
    if not result.ok:
        raise ValidationError(result.error or "Sandbox execution failed")
    return {"result": result.result, "summary": result.summary, "latency_ms": result.latency_ms}


async def _file_inspect(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from pathlib import Path

    dataset_id = args.get("dataset_id")
    path = ctx.dataset_paths.get(dataset_id or "", None)
    if not path or not Path(path).exists():
        raise ValidationError("Dataset file not found")
    import pandas as pd

    ext = Path(path).suffix.lower()
    df = pd.read_excel(path) if ext == ".xlsx" else pd.read_csv(path)
    return {
        "rows": int(len(df)),
        "columns": list(df.columns),
        "dtypes": {c: str(t) for c, t in df.dtypes.items()},
        "missing": {c: int(df[c].isna().sum()) for c in df.columns},
        "head": df.head(5).to_dict(orient="records"),
    }


async def _calculator(ctx: ToolContext, args: dict[str, Any]) -> Any:
    import ast as _ast

    expr = args["expression"]
    try:
        tree = _ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ValidationError(f"Invalid expression: {exc}") from exc
    for node in _ast.walk(tree):
        if isinstance(node, (_ast.Call, _ast.Attribute, _ast.Name)):
            if isinstance(node, _ast.Call):
                raise SecurityError("Function calls are not allowed in calculator")
            if isinstance(node, _ast.Attribute):
                raise SecurityError("Attribute access is not allowed in calculator")
    allowed_nodes = (
        _ast.Expression, _ast.BinOp, _ast.UnaryOp, _ast.Constant, _ast.Load,
        _ast.Add, _ast.Sub, _ast.Mult, _ast.Div, _ast.Pow, _ast.Mod, _ast.FloorDiv,
        _ast.USub, _ast.UAdd,
    )
    for node in _ast.walk(tree):
        if not isinstance(node, allowed_nodes):
            raise SecurityError(f"Calculator forbids node type {type(node).__name__}")
    value = eval(compile(tree, "<calc>", "eval"), {"__builtins__": {}}, {})  # noqa: S307 - AST-restricted
    return {"value": value}


async def _http_request(ctx: ToolContext, args: dict[str, Any]) -> Any:
    url = args["url"]
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    allow = settings.http_allowlist
    if host not in allow:
        raise SecurityError(f"Host '{host}' is not in the HTTP tool allowlist")
    method = args.get("method", "GET").upper()
    if method not in {"GET", "HEAD"}:
        raise SecurityError("Only GET/HEAD are permitted for the HTTP tool")
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
        resp = await client.request(method, url)
    return {"status": resp.status_code, "body": resp.text[:4000]}


def register_default_tools() -> None:
    if registry._tools:
        return
    registry.register(
        ToolSpec(
            name="document_search",
            description="Hybrid semantic+keyword search over ingested documents. Returns real citations.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer"},
                },
                "required": ["query"],
            },
            permission_level="LOW",
            timeout_seconds=20,
            handler=_doc_search,
        )
    )
    registry.register(
        ToolSpec(
            name="sql_query",
            description="Execute a read-only SQL query against the configured data source.",
            input_schema={
                "type": "object",
                "properties": {"sql": {"type": "string"}},
                "required": ["sql"],
            },
            permission_level="LOW",
            timeout_seconds=settings.sql_timeout_seconds,
            handler=_sql_query,
        )
    )
    registry.register(
        ToolSpec(
            name="python_analysis",
            description="Run sandboxed pandas analysis. Preload variable `df` when dataset_id given.",
            input_schema={
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "dataset_id": {"type": "string"},
                },
                "required": ["code"],
            },
            permission_level="MEDIUM",
            timeout_seconds=settings.sandbox_timeout_seconds + 5,
            handler=_python_analysis,
        )
    )
    registry.register(
        ToolSpec(
            name="file_inspect",
            description="Profile an uploaded dataset (shape, dtypes, missing values, head).",
            input_schema={
                "type": "object",
                "properties": {"dataset_id": {"type": "string"}},
                "required": ["dataset_id"],
            },
            permission_level="LOW",
            timeout_seconds=20,
            handler=_file_inspect,
        )
    )
    registry.register(
        ToolSpec(
            name="calculator",
            description="Safe arithmetic calculator (no function calls).",
            input_schema={
                "type": "object",
                "properties": {"expression": {"type": "string"}},
                "required": ["expression"],
            },
            permission_level="LOW",
            timeout_seconds=5,
            handler=_calculator,
        )
    )
    registry.register(
        ToolSpec(
            name="http_request",
            description="HTTP GET/HEAD against an allowlisted host.",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "method": {"type": "string"},
                },
                "required": ["url"],
            },
            permission_level="MEDIUM",
            timeout_seconds=20,
            handler=_http_request,
        )
    )
    # Example CRITICAL tool that always requires human approval
    registry.register(
        ToolSpec(
            name="admin_reset_metrics",
            description="CRITICAL: resets cached metric counters. Requires human approval.",
            input_schema={"type": "object", "properties": {}, "required": []},
            permission_level="CRITICAL",
            timeout_seconds=5,
            handler=lambda ctx, args: asyncio.sleep(0, result={"reset": True}),
        )
    )


async def execute_tool(
    ctx: ToolContext,
    name: str,
    args: dict[str, Any],
    *,
    auto_approve_high: bool = False,
) -> dict[str, Any]:
    """Permission check → validate → execute → audit. Raises ApprovalRequired for HIGH/CRITICAL."""
    register_default_tools()
    spec = registry.get(name)
    validate_args(spec.input_schema, args)

    needs_approval = RISK_ORDER.get(spec.permission_level, 1) >= 3 and not auto_approve_high
    if spec.permission_level == "MEDIUM" and ctx.user_role == "viewer":
        raise PermissionDeniedError("Viewer role cannot execute MEDIUM-risk tools")

    if needs_approval:
        approval = ApprovalRequest(
            task_id=ctx.task_id,
            action=f"tool:{name}",
            risk_level=spec.permission_level,
            payload={"tool": name, "args": args, "agent": ctx.agent},
            status="pending",
            requested_by=ctx.agent,
        )
        ctx.session.add(approval)
        ctx.session.add(
            AuditLog(
                actor=ctx.agent,
                action="tool.approval_requested",
                resource_type="tool",
                resource_id=name,
                details={"risk": spec.permission_level},
            )
        )
        await ctx.session.commit()
        await ctx.session.refresh(approval)
        raise ApprovalRequiredError(
            f"Tool '{name}' ({spec.permission_level}) requires human approval",
            approval_id=approval.id,
        )

    start = time.perf_counter()
    assert spec.handler is not None
    try:
        output = await asyncio.wait_for(spec.handler(ctx, args), timeout=spec.timeout_seconds)
        status = "success"
        error = None
    except (SecurityError, PermissionDeniedError, ApprovalRequiredError):
        raise
    except Exception as exc:  # noqa: BLE001
        output = None
        status = "error"
        error = str(exc)[:1000]
    latency = int((time.perf_counter() - start) * 1000)

    summary = str(output)[:2000] if output is not None else (error or "")
    ctx.session.add(
        ToolExecution(
            task_id=ctx.task_id,
            tool_name=name,
            agent=ctx.agent,
            arguments=args,
            output_summary=summary,
            status=status,
            latency_ms=latency,
            risk_level=spec.permission_level,
        )
    )
    ctx.session.add(
        AuditLog(
            actor=ctx.agent,
            action="tool.executed",
            resource_type="tool",
            resource_id=name,
            details={"status": status, "latency_ms": latency, "risk": spec.permission_level},
        )
    )
    await ctx.session.commit()
    if status == "error":
        raise ValidationError(error or "Tool failed")
    return {"tool": name, "output": output, "latency_ms": latency, "risk": spec.permission_level}


def catalog() -> list[dict[str, Any]]:
    register_default_tools()
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
            "permission_level": t.permission_level,
            "timeout_seconds": t.timeout_seconds,
        }
        for t in registry.list()
    ]


_ = utcnow
