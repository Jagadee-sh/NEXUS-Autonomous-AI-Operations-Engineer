"""Audit helpers and trace utilities."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.database.models import AuditLog


def new_trace_id() -> str:
    return str(uuid.uuid4())


async def audit(
    session: AsyncSession,
    *,
    actor: str,
    action: str,
    resource_type: str = "",
    resource_id: str = "",
    details: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    session.add(
        AuditLog(
            actor=actor,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details or {},
            ip=ip,
        )
    )
    await session.commit()


async def build_trace(session: AsyncSession, task) -> dict[str, Any]:
    from sqlalchemy import select

    from nexus.database.models import (
        CorrectionAttempt,
        Evidence,
        RetrievalResult,
        TaskStep,
        ToolExecution,
        ValidationResult,
    )

    steps = (
        (await session.execute(select(TaskStep).where(TaskStep.task_id == task.id).order_by(TaskStep.sequence)))
        .scalars()
        .all()
    )
    validations = (
        (await session.execute(select(ValidationResult).where(ValidationResult.task_id == task.id)))
        .scalars()
        .all()
    )
    corrections = (
        (await session.execute(select(CorrectionAttempt).where(CorrectionAttempt.task_id == task.id)))
        .scalars()
        .all()
    )
    evidence = (
        (await session.execute(select(Evidence).where(Evidence.task_id == task.id))).scalars().all()
    )
    tools = (
        (await session.execute(select(ToolExecution).where(ToolExecution.task_id == task.id)))
        .scalars()
        .all()
    )
    retrievals = (
        (await session.execute(select(RetrievalResult).where(RetrievalResult.task_id == task.id)))
        .scalars()
        .all()
    )

    timeline: list[dict[str, Any]] = []
    for s in steps:
        timeline.append(
            {
                "sequence": s.sequence,
                "agent": s.agent,
                "step_type": s.step_type,
                "status": s.status,
                "latency_ms": s.latency_ms,
                "input": s.input,
                "output": _truncate_output(s.output),
                "error": s.error,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
        )

    return {
        "task_id": task.id,
        "trace_id": task.trace_id,
        "status": task.status,
        "plan": task.plan,
        "retry_count": task.retry_count,
        "confidence": task.confidence,
        "timeline": timeline,
        "validations": [
            {
                "passed": v.passed,
                "score": v.score,
                "issues": v.issues,
                "unsupported_claims": v.unsupported_claims,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
            for v in validations
        ],
        "corrections": [
            {
                "failure_category": c.failure_category,
                "strategy": c.strategy,
                "description": c.description,
                "succeeded": c.succeeded,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in corrections
        ],
        "evidence": [
            {"claim": e.claim, "source_ref": e.source_ref, "excerpt": e.excerpt[:300], "strength": e.strength}
            for e in evidence
        ],
        "tool_calls": [
            {
                "tool": t.tool_name,
                "agent": t.agent,
                "status": t.status,
                "latency_ms": t.latency_ms,
                "risk_level": t.risk_level,
                "arguments": t.arguments,
            }
            for t in tools
        ],
        "retrievals": [
            {
                "query": r.query,
                "strategy": r.strategy,
                "score": r.score,
                "filename": (r.metadata_json or {}).get("filename"),
                "snippet": r.content_snippet[:200],
            }
            for r in retrievals[:50]
        ],
    }


def _truncate_output(output: dict[str, Any] | None) -> dict[str, Any]:
    if not output:
        return {}
    import json

    text = json.dumps(output, default=str)
    if len(text) <= 4000:
        return output
    return {"truncated": True, "preview": text[:4000]}
