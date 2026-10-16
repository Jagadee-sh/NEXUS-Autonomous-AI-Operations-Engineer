"""Agents, tools, approvals, evaluations, audit, auth, health."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus import __version__
from nexus.api.deps import AuthContext, get_auth_context, require_role
from nexus.core.exceptions import NotFoundError
from nexus.core.security import create_access_token, verify_password
from nexus.database.base import utcnow
from nexus.database.models import (
    Agent,
    ApprovalRequest,
    AuditLog,
    EvaluationDataset,
    EvaluationRun,
    Metric,
    Task,
    ToolExecution,
    User,
)
from nexus.database.session import get_session
from nexus.evaluation.runner import run_evaluation
from nexus.execution.sandbox import sandbox_info
from nexus.llm.registry import get_embedding_provider, get_llm_provider
from nexus.logging_config import get_logger
from nexus.orchestration.engine import run_workflow
from nexus.schemas.api import (
    ApprovalDecision,
    ApprovalOut,
    EvalDatasetCreate,
    EvalDatasetOut,
    EvalRunCreate,
    EvalRunOut,
    HealthOut,
    LoginRequest,
    ResearchCreate,
    TokenResponse,
    UserOut,
)
from nexus.tools.registry import catalog

log = get_logger("nexus.api")
agents_router = APIRouter(prefix="/agents", tags=["agents"])
tools_router = APIRouter(prefix="/tools", tags=["tools"])
approvals_router = APIRouter(prefix="/approvals", tags=["approvals"])
evaluations_router = APIRouter(prefix="/evaluations", tags=["evaluations"])
audit_router = APIRouter(prefix="/audit", tags=["audit"])
auth_router = APIRouter(prefix="/auth", tags=["auth"])
meta_router = APIRouter(tags=["meta"])

AGENT_PROFILES = [
    {"name": "planner", "role": "Planner", "description": "Decomposes the request into an executable plan.", "tools": []},
    {"name": "research", "role": "Research", "description": "Retrieves and synthesizes documentary evidence with citations.", "tools": ["document_search"]},
    {"name": "retrieval", "role": "Retrieval", "description": "Hybrid vector+BM25 retrieval with reranking.", "tools": ["document_search"]},
    {"name": "data_analyst", "role": "Data Analyst", "description": "Profiles datasets and runs sandboxed pandas analysis.", "tools": ["python_analysis", "file_inspect"]},
    {"name": "sql_analyst", "role": "SQL Analyst", "description": "Generates and executes read-only SQL.", "tools": ["sql_query"]},
    {"name": "tool_agent", "role": "Tool", "description": "Discovers and invokes governed tools.", "tools": ["*"]},
    {"name": "validator", "role": "Validator", "description": "Checks claims against evidence; triggers self-correction.", "tools": []},
    {"name": "report", "role": "Report", "description": "Assembles the executive answer with citations and confidence.", "tools": []},
]


@agents_router.get("")
async def list_agents(
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
) -> list[dict[str, Any]]:
    # merge registry table (if seeded) with built-in profiles + recent performance
    stored = {a.name: a for a in (await session.execute(select(Agent))).scalars()}
    recent = (
        await session.execute(select(Task.id).order_by(Task.created_at.desc()).limit(100))
    ).scalars().all()
    from nexus.database.models import TaskStep

    agent_statuses: dict[str, list[str]] = {}
    if recent:
        step_rows = (
            await session.execute(select(TaskStep).where(TaskStep.task_id.in_(list(recent))))
        ).scalars().all()
        for s in step_rows:
            agent_statuses.setdefault(s.agent, []).append(s.status)
    out = []
    for profile in AGENT_PROFILES:
        statuses = agent_statuses.get(profile["name"], [])
        total = len(statuses)
        succeeded = sum(1 for st in statuses if st == "success")
        out.append(
            {
                **profile,
                "is_active": stored.get(profile["name"]).is_active if profile["name"] in stored else True,
                "recent_executions": total,
                "success_rate": round(succeeded / total, 3) if total else None,
            }
        )
    return out


@tools_router.get("")
async def list_tools(ctx: Annotated[AuthContext, Depends(get_auth_context)]) -> list[dict[str, Any]]:
    return catalog()


@tools_router.get("/sandbox")
async def sandbox_details(ctx: Annotated[AuthContext, Depends(get_auth_context)]) -> dict[str, Any]:
    return sandbox_info()


@approvals_router.get("", response_model=list[ApprovalOut])
async def list_approvals(
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    status: str = "pending",
) -> list[ApprovalRequest]:
    return list(
        (
            await session.execute(
                select(ApprovalRequest).where(ApprovalRequest.status == status).order_by(ApprovalRequest.created_at.desc())
            )
        ).scalars()
    )


@approvals_router.post("/{approval_id}/approve", response_model=ApprovalOut)
async def approve(
    approval_id: str,
    body: ApprovalDecision,
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[AuthContext, Depends(require_role("analyst"))],
) -> ApprovalRequest:
    req = await session.get(ApprovalRequest, approval_id)
    if not req:
        raise NotFoundError("Approval not found")
    if req.status != "pending":
        return req
    req.status = "approved"
    req.decided_by = ctx.email or ctx.role
    req.decided_at = utcnow()
    req.reason = body.reason or "approved"
    await session.commit()
    await session.refresh(req)

    # execute the approved tool call if it was blocked on this approval
    payload = req.payload or {}
    if payload.get("tool") and req.task_id:
        from nexus.database.models import Task as TaskModel
        from nexus.tools.registry import ToolContext, execute_tool

        task = await session.get(TaskModel, req.task_id)
        if task:
            ctx_tool = ToolContext(
                session=session,
                task_id=task.id,
                agent="approval_executor",
                user_role=ctx.role,
                document_ids=(task.context or {}).get("document_ids") or None,
                datasource_url=None,
            )
            try:
                await execute_tool(
                    ctx_tool, payload["tool"], payload.get("args", {}), auto_approve_high=True
                )
                session.add(
                    AuditLog(
                        actor=ctx.email or ctx.role,
                        action="approval.executed",
                        resource_type="tool",
                        resource_id=payload["tool"],
                        details={"result_ok": True, "approval_id": req.id},
                    )
                )
                await session.commit()
                log.info("approved tool executed: %s", payload["tool"])
            except Exception as exc:  # noqa: BLE001
                log.warning("approved tool execution failed: %s", exc)
    return req


@approvals_router.post("/{approval_id}/reject", response_model=ApprovalOut)
async def reject(
    approval_id: str,
    body: ApprovalDecision,
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[AuthContext, Depends(require_role("analyst"))],
) -> ApprovalRequest:
    req = await session.get(ApprovalRequest, approval_id)
    if not req:
        raise NotFoundError("Approval not found")
    if req.status != "pending":
        return req
    req.status = "rejected"
    req.decided_by = ctx.email or ctx.role
    req.decided_at = utcnow()
    req.reason = body.reason or "rejected"
    await session.commit()
    await session.refresh(req)
    return req


@evaluations_router.post("/datasets", response_model=EvalDatasetOut)
async def create_eval_dataset(
    body: EvalDatasetCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[AuthContext, Depends(require_role("analyst"))],
) -> EvaluationDataset:
    ds = EvaluationDataset(name=body.name, description=body.description, items=body.items)
    session.add(ds)
    await session.commit()
    await session.refresh(ds)
    return ds


@evaluations_router.get("/datasets", response_model=list[EvalDatasetOut])
async def list_eval_datasets(
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
) -> list[EvaluationDataset]:
    return list((await session.execute(select(EvaluationDataset))).scalars())


@evaluations_router.post("/run", response_model=EvalRunOut)
async def start_eval_run(
    body: EvalRunCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[AuthContext, Depends(require_role("analyst"))],
) -> EvaluationRun:
    return await run_evaluation(session, body.dataset_id)


@evaluations_router.get("/runs", response_model=list[EvalRunOut])
async def list_eval_runs(
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
) -> list[EvaluationRun]:
    return list(
        (await session.execute(select(EvaluationRun).order_by(EvaluationRun.created_at.desc()).limit(50))).scalars()
    )


@evaluations_router.get("/runs/{run_id}", response_model=EvalRunOut)
async def get_eval_run(
    run_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
) -> EvaluationRun:
    run = await session.get(EvaluationRun, run_id)
    if not run:
        raise NotFoundError("Run not found")
    return run


@evaluations_router.get("/runs/{run_id}/metrics", response_model=list[dict[str, Any]])
async def get_run_metrics(
    run_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
) -> list[dict[str, Any]]:
    rows = (await session.execute(select(Metric).where(Metric.run_id == run_id))).scalars()
    return [{"name": m.name, "value": m.value, "slice": m.slice} for m in rows]


@evaluations_router.post("/research/retrieval-comparison", response_model=EvalRunOut)
async def start_retrieval_research(
    body: ResearchCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[AuthContext, Depends(require_role("analyst"))],
) -> EvaluationRun:
    from nexus.research.strategies import run_retrieval_comparison

    return await run_retrieval_comparison(
        session, dataset_id=body.dataset_id, questions=body.questions, top_k=body.top_k
    )


@evaluations_router.get("/research/retrieval-comparison", response_model=EvalRunOut | None)
async def latest_retrieval_research(
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
) -> EvaluationRun | None:
    from nexus.research.strategies import RESEARCH_DATASET_NAME

    ds = (
        await session.execute(
            select(EvaluationDataset).where(EvaluationDataset.name == RESEARCH_DATASET_NAME)
        )
    ).scalars().first()
    if not ds:
        return None
    return (
        await session.execute(
            select(EvaluationRun)
            .where(EvaluationRun.dataset_id == ds.id)
            .order_by(EvaluationRun.created_at.desc())
            .limit(1)
        )
    ).scalars().first()


@audit_router.get("")
async def list_audit(
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[AuthContext, Depends(require_role("admin"))],
    limit: int = Query(default=100, le=500),
) -> list[dict[str, Any]]:
    rows = (await session.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit))).scalars()
    return [
        {
            "id": r.id,
            "actor": r.actor,
            "action": r.action,
            "resource_type": r.resource_type,
            "resource_id": r.resource_id,
            "details": r.details,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@auth_router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenResponse:
    from sqlalchemy.orm import selectinload

    user = (
        (
            await session.execute(
                select(User).options(selectinload(User.role)).where(User.email == body.email)
            )
        )
        .scalars()
        .first()
    )
    if not user or not verify_password(body.password, user.hashed_password):
        from nexus.core.exceptions import PermissionDeniedError

        raise PermissionDeniedError("Invalid email or password")
    token = create_access_token(user.email, user.role.name if user.role else "analyst")
    return TokenResponse(access_token=token, user=UserOut(id=user.id, email=user.email, full_name=user.full_name, role=user.role.name if user.role else "analyst"))


@auth_router.get("/me", response_model=UserOut)
async def me(
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
) -> UserOut:
    if ctx.email:
        from sqlalchemy.orm import selectinload

        user = (
            (
                await session.execute(
                    select(User).options(selectinload(User.role)).where(User.email == ctx.email)
                )
            )
            .scalars()
            .first()
        )
        if user:
            return UserOut(id=user.id, email=user.email, full_name=user.full_name, role=user.role.name if user.role else "analyst")
    return UserOut(id=ctx.user_id or "anonymous", email=ctx.email or "anonymous@nexus.local", full_name="", role=ctx.role)


@meta_router.get("/health", response_model=HealthOut, tags=["health"])
async def health() -> HealthOut:
    return HealthOut(status="ok", version=__version__, time=datetime.now(UTC))


@meta_router.get("/ready", tags=["health"])
async def ready(session: Annotated[AsyncSession, Depends(get_session)]) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    try:
        await session.execute(select(1))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"error: {exc}"
    try:
        if __import__("nexus.config", fromlist=["settings"]).settings.redis_url:
            import redis as redis_sync

            r = redis_sync.from_url(__import__("nexus.config", fromlist=["settings"]).settings.redis_url, socket_connect_timeout=1)
            r.ping()
            checks["redis"] = "ok"
        else:
            checks["redis"] = "disabled (in-process queue)"
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = f"error: {exc}"
    checks["vector_store"] = __import__("nexus.config", fromlist=["settings"]).settings.vector_store
    llm = get_llm_provider()
    emb = get_embedding_provider()
    checks["llm_provider"] = f"{llm.name} healthy={llm.healthy()}"
    checks["embedding_provider"] = f"{emb.name} healthy={emb.healthy()}"
    status = "ok" if all(str(v).startswith("ok") or "disabled" in str(v) for k, v in checks.items() if k in {"database"}) else "degraded"
    return {"status": status, "checks": checks}


_ = run_workflow
_ = ToolExecution
