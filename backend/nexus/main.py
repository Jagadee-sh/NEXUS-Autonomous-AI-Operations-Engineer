"""FastAPI application factory."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from nexus import __version__
from nexus.api.v1.admin import (
    agents_router,
    approvals_router,
    audit_router,
    auth_router,
    evaluations_router,
    meta_router,
    tools_router,
)
from nexus.api.v1.demo import router as demo_router
from nexus.api.v1.knowledge import datasets_router, datasources_router, documents_router
from nexus.api.v1.tasks import query_router
from nexus.api.v1.tasks import router as tasks_router
from nexus.config import settings
from nexus.core.exceptions import NexusError
from nexus.database.models import ApprovalRequest, Dataset, Document, Task
from nexus.database.session import get_session_factory, init_db
from nexus.logging_config import get_logger, setup_logging
from nexus.tools.registry import register_default_tools
from nexus.workers.queue import get_queue

log = get_logger("nexus.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings.storage_path.mkdir(parents=True, exist_ok=True)
    await init_db()
    from nexus.core.bootstrap import ensure_default_users
    from nexus.database.session import get_session_factory

    async with get_session_factory()() as _bootstrap_session:
        await ensure_default_users(_bootstrap_session)
    register_default_tools()
    queue = get_queue()
    await queue.start(lambda _tid: _noop(), poll_interval=settings.worker_poll_interval)
    log.info("NEXUS API started (env=%s, llm=%s)", settings.nexus_env, settings.llm_provider)
    try:
        yield
    finally:
        await queue.stop()


async def _noop() -> None:
    return None


def create_app() -> FastAPI:
    app = FastAPI(
        title="NEXUS — Autonomous Enterprise Intelligence Fabric",
        version=__version__,
        description="Enterprise AI control plane: ingestion, RAG, agents, SQL, sandboxed Python, tools, validation, self-correction, evaluation, audit.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(NexusError)
    async def nexus_error_handler(request: Request, exc: NexusError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Process-Time-Ms"] = str(int((time.perf_counter() - start) * 1000))
        return response

    prefix = settings.api_prefix
    app.include_router(meta_router)  # /health, /ready at root
    app.include_router(auth_router, prefix=prefix)
    app.include_router(tasks_router, prefix=prefix)
    app.include_router(query_router, prefix=prefix)
    app.include_router(documents_router, prefix=prefix)
    app.include_router(datasets_router, prefix=prefix)
    app.include_router(datasources_router, prefix=prefix)
    app.include_router(agents_router, prefix=prefix)
    app.include_router(tools_router, prefix=prefix)
    app.include_router(approvals_router, prefix=prefix)
    app.include_router(evaluations_router, prefix=prefix)
    app.include_router(audit_router, prefix=prefix)
    app.include_router(demo_router, prefix=prefix)

    @app.get(f"{prefix}/stats")
    async def stats(request: Request) -> dict[str, Any]:
        factory = get_session_factory()
        async with factory() as session:
            total_tasks = (await session.execute(select(func.count(Task.id)))).scalar() or 0
            by_status = {
                row[0]: row[1]
                for row in (
                    await session.execute(select(Task.status, func.count(Task.id)).group_by(Task.status))
                ).all()
            }
            docs = (await session.execute(select(func.count(Document.id)))).scalar() or 0
            ready_docs = (
                await session.execute(select(func.count(Document.id)).where(Document.status == "ready"))
            ).scalar() or 0
            datasets_n = (await session.execute(select(func.count(Dataset.id)))).scalar() or 0
            pending_approvals = (
                await session.execute(select(func.count(ApprovalRequest.id)).where(ApprovalRequest.status == "pending"))
            ).scalar() or 0
            recent = (await session.execute(select(Task).order_by(Task.created_at.desc()).limit(8))).scalars().all()
            confidences = [t.confidence for t in (await session.execute(select(Task).where(Task.confidence.is_not(None)))).scalars() if t.confidence is not None]
            latencies = []
            for t in recent:
                if t.started_at and t.finished_at:
                    latencies.append((t.finished_at - t.started_at).total_seconds())
            total_done = by_status.get("succeeded", 0) + by_status.get("failed", 0)
            return {
                "tasks_total": total_tasks,
                "tasks_by_status": by_status,
                "success_rate": round(by_status.get("succeeded", 0) / total_done, 3) if total_done else None,
                "documents": {"total": docs, "ready": ready_docs},
                "datasets": datasets_n,
                "pending_approvals": pending_approvals,
                "avg_confidence": round(sum(confidences) / len(confidences), 3) if confidences else None,
                "avg_latency_seconds": round(sum(latencies) / len(latencies), 2) if latencies else None,
                "recent_tasks": [
                    {
                        "id": t.id,
                        "title": t.title,
                        "status": t.status,
                        "confidence": t.confidence,
                        "created_at": t.created_at.isoformat() if t.created_at else None,
                    }
                    for t in recent
                ],
                "llm_provider": settings.llm_provider,
                "embedding_provider": settings.embedding_provider,
                "vector_store": settings.vector_store,
            }

    return app


app = create_app()
