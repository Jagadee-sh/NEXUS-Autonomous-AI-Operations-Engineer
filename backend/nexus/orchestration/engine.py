"""Workflow engine: stateful graph with conditional routing and bounded retries."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.agents import core as agents
from nexus.config import settings
from nexus.database.base import utcnow
from nexus.database.models import (
    AgentExecution,
    CorrectionAttempt,
    Dataset,
    DataSource,
    Document,
    Evidence,
    ExecutionEvent,
    Task,
    TaskStep,
    ValidationResult,
)
from nexus.logging_config import get_logger
from nexus.observability.tracing import redact_trace_payload
from nexus.orchestration.state import WorkflowState
from nexus.self_correction.classifier import build_correction_note, classify_failures

log = get_logger("nexus.orchestration")


class TraceRecorder:
    def __init__(self, session: AsyncSession, task_id: str, trace_id: str):
        self.session = session
        self.task_id = task_id
        self.trace_id = trace_id
        self.seq = 0

    async def event(
        self,
        event_type: str,
        component: str,
        *,
        payload: dict | None = None,
        status: str = "success",
        latency_ms: int = 0,
    ) -> None:
        self.seq += 1
        self.session.add(
            ExecutionEvent(
                task_id=self.task_id,
                trace_id=self.trace_id,
                sequence=self.seq,
                event_type=event_type,
                component=component,
                status=status,
                payload=redact_trace_payload(payload),
                latency_ms=latency_ms,
            )
        )
        await self.session.commit()

    async def step(
        self,
        agent: str,
        step_type: str,
        *,
        input: dict | None = None,
        output: dict | None = None,
        status: str = "success",
        error: str | None = None,
        latency_ms: int = 0,
    ) -> None:
        self.seq += 1
        self.session.add(
            TaskStep(
                task_id=self.task_id,
                sequence=self.seq,
                agent=agent,
                step_type=step_type,
                status=status,
                input=input or {},
                output=output or {},
                error=error,
                latency_ms=latency_ms,
            )
        )
        await self.session.commit()
        await self.event(
            "agent_step",
            agent,
            payload={"step_type": step_type, "input": input or {}, "output": output or {}, "error": error},
            status=status,
            latency_ms=latency_ms,
        )


async def _timed(fn: Callable[[], Awaitable[Any]]) -> tuple[Any, int]:
    start = time.perf_counter()
    result = await fn()
    return result, int((time.perf_counter() - start) * 1000)


async def prepare_state(session: AsyncSession, task: Task) -> WorkflowState:
    ctx = task.context or {}
    state = WorkflowState(
        task_id=task.id,
        trace_id=task.trace_id or str(uuid.uuid4()),
        request=task.request,
        user_id=task.user_id,
        user_role=ctx.get("user_role", "analyst"),
        document_ids=ctx.get("document_ids", []) or [],
        dataset_ids=ctx.get("dataset_ids", []) or [],
        datasource_id=ctx.get("datasource_id"),
        max_retries=task.max_retries or settings.max_retries,
        metadata={"session": session},
    )
    # resolve dataset paths
    for ds_id in state.dataset_ids:
        ds = await session.get(Dataset, ds_id)
        if ds:
            state.dataset_paths[ds_id] = ds.storage_path
    if state.datasource_id:
        src = await session.get(DataSource, state.datasource_id)
        if src:
            state.datasource_url = src.connection_url
            from nexus.execution.sql_engine import async_discover_schema

            try:
                state.schema = await async_discover_schema(src.connection_url)
            except Exception as exc:  # noqa: BLE001
                state.errors.append(f"schema discovery failed: {exc}")
    if not state.document_ids:
        rows = await session.execute(select(Document.id).where(Document.status == "ready").limit(50))
        state.document_ids = list(rows.scalars())
    return state


async def run_workflow(session: AsyncSession, task_id: str) -> Task:
    task = await session.get(Task, task_id)
    if not task:
        raise ValueError(f"Task {task_id} not found")
    task.status = "running"
    task.started_at = utcnow()
    if not task.trace_id:
        task.trace_id = str(uuid.uuid4())
    await session.commit()

    state = await prepare_state(session, task)
    ctx = task.context or {}
    if isinstance(ctx.get("failure_injection"), dict):
        state.metadata["failure_injection"] = dict(ctx["failure_injection"])
    trace = TraceRecorder(session, task.id, task.trace_id)
    await trace.event("workflow_started", "orchestrator", payload={"request": task.request[:500]})

    exec_row = AgentExecution(task_id=task.id, agent="orchestrator", iteration=0, status="running")
    session.add(exec_row)
    await session.commit()

    try:
        await _run_loop(session, task, state, trace)

        for row in state.evidence:
            session.add(
                Evidence(
                    task_id=task.id,
                    claim=row.claim,
                    source_ref=row.source_ref,
                    excerpt=row.excerpt,
                    strength=row.strength,
                )
            )
        task.plan = state.plan.model_dump() if state.plan else None
        task.result = {
            "answer": state.final_answer,
            "findings": [f.model_dump() for f in state.findings[:12]],
            "citations": sorted({d.citation() for d in state.retrieved_documents}),
            "corrections": state.correction_history,
            "summary": state.summary_dict(),
        }
        task.confidence = state.confidence
        task.retry_count = state.retry_count
        task.status = "succeeded"
        task.finished_at = utcnow()
        exec_row.status = "success"
        exec_row.finished_at = utcnow()
        await session.commit()
        await trace.event("workflow_finished", "orchestrator", payload={"status": task.status})
    except Exception as exc:  # noqa: BLE001
        log.exception("workflow failed for task %s", task.id)
        task.status = "failed"
        task.error = str(exc)[:2000]
        task.finished_at = utcnow()
        exec_row.status = "failed"
        exec_row.finished_at = utcnow()
        await session.commit()
        await trace.event("workflow_finished", "orchestrator", payload={"status": task.status, "error": str(exc)[:500]}, status="failed")
    finally:
        state.metadata.pop("session", None)
    await session.refresh(task)
    return task


async def _run_loop(session: AsyncSession, task: Task, state: WorkflowState, trace: TraceRecorder) -> None:
    # 1) Plan
    plan, plan_ms = await _timed(lambda: agents.planner_agent(state, session))
    await trace.step("planner", "plan", input={"request": task.request[:500]}, output=plan.model_dump(), latency_ms=plan_ms)
    task.plan = plan.model_dump()
    await session.commit()

    # persist agent profiles for dashboard
    # 2) Execute plan steps (workers) until validator decision
    while True:
        state.iteration += 1
        if state.iteration > settings.max_agent_iterations:
            state.errors.append("Max agent iterations exceeded")
            break

        for step in plan.steps:
            if step.status in {"done", "skipped"}:
                continue
            if step.agent == "validator":
                continue
            step.status = "running"
            await session.commit()
            try:
                if step.agent == "data_analyst":
                    out, ms = await _timed(lambda s=step: agents.data_analyst_agent(state, s.goal))
                elif step.agent == "sql_analyst":
                    out, ms = await _timed(lambda s=step: agents.sql_analyst_agent(state, s.goal))
                elif step.agent == "research":
                    out, ms = await _timed(lambda s=step: agents.research_agent(state, s.goal))
                elif step.agent == "tool":
                    out, ms = await _timed(lambda s=step: agents.tool_agent(state, "document_search", {"query": s.goal}))
                elif step.agent == "report":
                    out, ms = await _timed(lambda: agents.report_agent(state))
                else:
                    step.status = "skipped"
                    continue
                step.status = "done"
                step.output = out if isinstance(out, dict) else {"result": str(out)[:1000]}
                await trace.step(step.agent, _step_type(step.agent), input={"goal": step.goal}, output=step.output, latency_ms=ms)
            except Exception as exc:  # noqa: BLE001
                step.status = "failed"
                step.error = str(exc)[:1000]
                state.errors.append(f"{step.agent}: {exc}")
                await trace.step(step.agent, _step_type(step.agent), input={"goal": step.goal}, status="failed", error=str(exc)[:1000])
            await session.commit()

        # if plan had no research but documents exist and no evidence collected, retrieve
        if not state.evidence and state.document_ids:
            out, ms = await _timed(lambda: agents.research_agent(state, state.request))
            await trace.step("research", "retrieve", input={"goal": state.request[:200]}, output=out if isinstance(out, dict) else {}, latency_ms=ms)

        # draft answer (report if not already produced by a plan step)
        if not state.final_answer:
            out, ms = await _timed(lambda: agents.report_agent(state))
            await trace.step("report", "report", output=out if isinstance(out, dict) else {}, latency_ms=ms)

        # 3) Validate
        draft = state.final_answer or ""
        validation = agents.validate_state(state, draft)
        validation = _apply_failure_injection(state, validation)
        vr = ValidationResult(
            task_id=task.id,
            passed=validation["passed"],
            score=validation["score"],
            issues=validation["issues"],
            unsupported_claims=validation["unsupported_claims"],
        )
        session.add(vr)
        await trace.step("validator", "validate", output=validation)
        await session.commit()

        if validation["passed"]:
            if state.retry_count > 0:
                pending = (
                    (
                        await session.execute(
                            select(CorrectionAttempt).where(
                                CorrectionAttempt.task_id == task.id,
                                CorrectionAttempt.succeeded.is_(False),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for attempt in pending:
                    attempt.succeeded = True
                if pending:
                    await session.commit()
            break

        # 4) Self-correct
        if state.retry_count >= state.max_retries:
            state.errors.append("Max retries reached; accepting best-effort answer")
            await trace.step("orchestrator", "correct", status="failed", error="max_retries_exceeded")
            break

        diagnoses = classify_failures(state, validation)
        state.retry_count += 1
        note = build_correction_note(diagnoses, state.retry_count)
        state.correction_history.append(
            {"retry": state.retry_count, "diagnoses": [d.__dict__ for d in diagnoses], "note": note}
        )
        session.add(
            CorrectionAttempt(
                task_id=task.id,
                failure_category=",".join(d.category for d in diagnoses) or "unsupported_claim",
                strategy=",".join(d.strategy for d in diagnoses) or "query_rewrite",
                description=note,
                succeeded=False,
            )
        )
        await trace.step("self_correction", "correct", output={"note": note, "diagnoses": [d.__dict__ for d in diagnoses]})

        # apply strategy: reset steps + adjust state
        for step in plan.steps:
            if step.status == "failed":
                step.status = "pending"
        state.final_answer = None
        # broaden retrieval for poor retrieval / unsupported claims
        if any(d.category in {"poor_retrieval", "unsupported_claim", "missing_evidence"} for d in diagnoses) and state.document_ids:
            from nexus.retrieval.hybrid import RetrievalQuery, hybrid_retrieve

            query = RetrievalQuery(
                text=f"{state.request} {note}",
                document_ids=state.document_ids or None,
                top_k=10,
                strategy="keyword" if state.retry_count % 2 else "hybrid",
            )
            hits = await hybrid_retrieve(session, query)
            from nexus.orchestration.state import RetrievedDoc

            state.retrieved_documents = [
                RetrievedDoc(
                    chunk_id=h.chunk_id,
                    document_id=h.document_id,
                    filename=h.filename,
                    page=h.page,
                    section=h.section,
                    content=h.content,
                    score=h.score,
                    metadata=h.metadata or {},
                )
                for h in hits
            ]
        # retry loop continues
    # end while


def _step_type(agent: str) -> str:
    return {
        "data_analyst": "analyze",
        "sql_analyst": "sql",
        "research": "retrieve",
        "retrieval": "retrieve",
        "tool": "tool",
        "report": "report",
        "planner": "plan",
        "validator": "validate",
    }.get(agent, "step")


def _apply_failure_injection(state: WorkflowState, validation: dict) -> dict:
    """Demo/test hook: deterministically fail the first validation round.

    Triggered by task context ``failure_injection = {"category": ..., "fail_first": n}``.
    Used by flagship demo #2 to *show* the self-correction loop operating on a
    real (simulated) failure, after which validation runs normally.
    """
    inj = state.metadata.get("failure_injection")
    if not isinstance(inj, dict):
        return validation
    remaining = int(inj.get("fail_first", 1) or 0)
    if remaining <= 0 or state.metadata.get("injection_consumed"):
        return validation
    state.metadata["injection_consumed"] = True
    inj["fail_first"] = remaining - 1
    category = str(inj.get("category", "poor_retrieval"))
    forced = dict(validation)
    forced["passed"] = False
    forced["score"] = 0.0
    forced["injected"] = True
    forced["issues"] = list(forced.get("issues") or []) + [
        f"[demo injection] simulated failure: {category}"
    ]
    # steer classification toward the requested category
    if category in {"poor_retrieval", "missing_evidence", "insufficient_context"}:
        forced["retrieval_ok"] = False
    if category in {"unsupported_claim"}:
        forced["unsupported_claims"] = list(forced.get("unsupported_claims") or []) + [
            "Injected unsupported claim for demonstration purposes."
        ]
    if category in {"sql_execution_failure", "invalid_sql"}:
        forced["sql_ok"] = False
    if category in {"python_execution_failure"}:
        forced["analysis_ok"] = False
    if category == "timeout":
        state.errors.append("[demo injection] simulated step timeout")
    return forced


_ = json
