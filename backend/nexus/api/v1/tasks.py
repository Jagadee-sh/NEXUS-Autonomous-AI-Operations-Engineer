"""Task / query endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.api.deps import AuthContext, get_auth_context
from nexus.core.exceptions import NotFoundError
from nexus.database.models import Message, Task
from nexus.database.session import get_session
from nexus.observability.tracing import build_trace
from nexus.orchestration.engine import run_workflow
from nexus.schemas.api import QueryRequest, TaskCreate, TaskOut
from nexus.workers.queue import get_queue

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=TaskOut)
async def create_task(
    body: TaskCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
) -> Task:
    task = Task(
        title=body.title or body.request[:80],
        request=body.request,
        priority=body.priority,
        user_id=ctx.user_id,
        trace_id=str(uuid.uuid4()),
        max_retries=body.max_retries if body.max_retries is not None else 3,
        context={
            "document_ids": body.document_ids,
            "dataset_ids": body.dataset_ids,
            "datasource_id": body.datasource_id,
            "user_role": ctx.role,
            "failure_injection": body.failure_injection,
        },
    )
    session.add(task)
    session.add(Message(task_id=task.id, role="user", content=body.request))
    await session.commit()
    await session.refresh(task)
    await get_queue().enqueue(task.id)
    return task


@router.get("", response_model=list[TaskOut])
async def list_tasks(
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    status: str | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
) -> list[Task]:
    stmt = select(Task).order_by(Task.created_at.desc()).limit(limit).offset(offset)
    if status:
        stmt = stmt.where(Task.status == status)
    return list((await session.execute(stmt)).scalars())


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(
    task_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
) -> Task:
    task = await session.get(Task, task_id)
    if not task:
        raise NotFoundError("Task not found")
    return task


@router.get("/{task_id}/trace")
async def get_trace(
    task_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
) -> dict[str, Any]:
    task = await session.get(Task, task_id)
    if not task:
        raise NotFoundError("Task not found")
    return await build_trace(session, task)


@router.post("/{task_id}/cancel", response_model=TaskOut)
async def cancel_task(
    task_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
) -> Task:
    task = await session.get(Task, task_id)
    if not task:
        raise NotFoundError("Task not found")
    if task.status == "queued":
        task.status = "cancelled"
        await session.commit()
        await session.refresh(task)
    return task


query_router = APIRouter(tags=["query"])


@query_router.post("/query")
async def query(
    body: QueryRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
) -> dict[str, Any]:
    task = Task(
        title=body.question[:80],
        request=body.question,
        trace_id=str(uuid.uuid4()),
        context={
            "document_ids": body.document_ids,
            "dataset_ids": body.dataset_ids,
            "datasource_id": body.datasource_id,
            "user_role": ctx.role,
            "failure_injection": body.failure_injection,
        },
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    if body.wait:
        task = await run_workflow(session, task.id)
        return {
            "task_id": task.id,
            "status": task.status,
            "answer": (task.result or {}).get("answer"),
            "confidence": task.confidence,
            "citations": (task.result or {}).get("citations", []),
            "trace_id": task.trace_id,
            "result": task.result,
        }
    await get_queue().enqueue(task.id)
    return {"task_id": task.id, "status": task.status, "trace_id": task.trace_id}
