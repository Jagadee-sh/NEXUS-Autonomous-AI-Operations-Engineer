"""Tool permission + approval workflow tests."""

from __future__ import annotations

import pytest

from nexus.core.exceptions import ApprovalRequiredError, SecurityError, ValidationError
from nexus.database.models import ApprovalRequest
from nexus.tools.registry import ToolContext, catalog, execute_tool, register_default_tools, registry


async def test_calculator_tool(session):
    ctx = ToolContext(session=session)
    out = await execute_tool(ctx, "calculator", {"expression": "2 + 3 * 4"})
    assert out["output"]["value"] == 14


async def test_calculator_rejects_calls(session):
    ctx = ToolContext(session=session)
    with pytest.raises((ValidationError, SecurityError)):
        await execute_tool(ctx, "calculator", {"expression": "__import__('os').getcwd()"})


async def test_http_tool_allowlist(session):
    ctx = ToolContext(session=session)
    with pytest.raises(SecurityError):
        await execute_tool(ctx, "http_request", {"url": "http://evil.example.com/x"})


async def test_critical_tool_requires_approval(session):
    ctx = ToolContext(session=session, task_id=None, agent="tester")
    with pytest.raises(ApprovalRequiredError) as exc:
        await execute_tool(ctx, "admin_reset_metrics", {})
    assert exc.value.approval_id
    row = await session.get(ApprovalRequest, exc.value.approval_id)
    assert row is not None and row.status == "pending" and row.risk_level == "CRITICAL"


async def test_low_tool_audited(session):
    ctx = ToolContext(session=session, agent="tester")
    await execute_tool(ctx, "calculator", {"expression": "1+1"})
    from sqlalchemy import select

    from nexus.database.models import ToolExecution

    rows = (await session.execute(select(ToolExecution))).scalars().all()
    assert any(r.tool_name == "calculator" and r.status == "success" for r in rows)


def test_catalog_has_schemas():
    cat = catalog()
    names = {c["name"] for c in cat}
    assert {"document_search", "sql_query", "python_analysis", "calculator", "http_request"} <= names
    for c in cat:
        assert "input_schema" in c and "permission_level" in c


_ = registry, register_default_tools
