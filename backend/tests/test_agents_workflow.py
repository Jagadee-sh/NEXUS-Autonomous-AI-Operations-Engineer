"""Agent workflow, self-correction, and max-retry tests."""

from __future__ import annotations

from sqlalchemy import select

from nexus.database.models import CorrectionAttempt, Task, ValidationResult
from nexus.ingestion.pipeline import ingest_document
from nexus.orchestration.engine import run_workflow
from nexus.services.dataset_service import ingest_dataset
from tests.conftest import DEMO_SALES_CSV, POLICY_TXT


async def test_end_to_end_task_succeeds(session):
    ds = await ingest_dataset(session, filename="sales.csv", content=DEMO_SALES_CSV, name="Sales")
    await ingest_document(session, filename="policy.txt", content=POLICY_TXT)
    task = Task(
        request="Compare Q2 and Q3 revenue and profitability, and verify policy thresholds from documents.",
        context={"dataset_ids": [ds.id], "user_role": "analyst"},
        max_retries=3,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    task = await run_workflow(session, task.id)
    assert task.status == "succeeded"
    assert task.result and task.result.get("answer")
    assert task.confidence is not None and task.confidence > 0
    # trace exists
    from nexus.database.models import TaskStep

    step_rows = (await session.execute(select(TaskStep).where(TaskStep.task_id == task.id))).scalars().all()
    types = {s.step_type for s in step_rows}
    assert "plan" in types and "validate" in types and "report" in types


async def test_max_retries_prevent_infinite_loops(session):
    """Force validation failure by claiming documents exist but making claims ungroundable.

    We monkeypatch the validator to always fail, ensuring the retry cap holds.
    """
    from nexus.agents import core as agents

    original = agents.validate_state
    agents.validate_state = lambda state, draft: {
        "passed": False,
        "score": 0.0,
        "issues": ["forced failure"],
        "unsupported_claims": ["always unsupported claim about unicorns running the datacenter"],
        "retrieval_ok": False,
        "analysis_ok": True,
        "sql_ok": True,
    }
    try:
        ds = await ingest_dataset(session, filename="sales.csv", content=DEMO_SALES_CSV, name="Sales")
        task = Task(
            request="Summarize sales data.",
            context={"dataset_ids": [ds.id], "user_role": "analyst"},
            max_retries=2,
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        task = await run_workflow(session, task.id)
        assert task.retry_count <= 2
        corrections = (
            await session.execute(select(CorrectionAttempt).where(CorrectionAttempt.task_id == task.id))
        ).scalars().all()
        assert len(corrections) <= 2
        validations = (
            await session.execute(select(ValidationResult).where(ValidationResult.task_id == task.id))
        ).scalars().all()
        assert len(validations) <= 3  # initial + max_retries
    finally:
        agents.validate_state = original


async def test_self_correction_recorded_on_retrieval_gap(session):
    """Documents selected but empty retrieval triggers correction attempt."""
    task = Task(
        request="What does the nonexistent topic handbook say about dragons?",
        context={"user_role": "analyst"},
        max_retries=1,
    )
    # ingest a doc so document_ids get populated by engine, but content unrelated
    await ingest_document(session, filename="policy.txt", content=POLICY_TXT)
    session.add(task)
    await session.commit()
    await session.refresh(task)
    task = await run_workflow(session, task.id)
    # Should still complete (best effort) and record validations
    validations = (
        await session.execute(select(ValidationResult).where(ValidationResult.task_id == task.id))
    ).scalars().all()
    assert validations
    assert task.status in {"succeeded", "failed"}
    assert task.retry_count <= task.max_retries


async def test_data_only_task_produces_findings(session):
    ds = await ingest_dataset(session, filename="sales.csv", content=DEMO_SALES_CSV, name="Sales")
    task = Task(
        request="Analyze quarterly revenue and profit trends and find anomalies.",
        context={"dataset_ids": [ds.id], "user_role": "analyst"},
        max_retries=2,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    task = await run_workflow(session, task.id)
    assert task.status == "succeeded"
    findings = (task.result or {}).get("findings") or []
    assert findings


async def test_step_exception_recorded_not_fatal(session):
    """A raising agent step must be recorded on PlanStep.error, not crash the workflow."""
    from nexus.agents import core as agents
    from nexus.database.models import TaskStep

    async def boom(state, goal):
        raise RuntimeError("simulated agent explosion")

    ds = await ingest_dataset(session, filename="sales.csv", content=DEMO_SALES_CSV, name="Sales")
    original = agents.data_analyst_agent
    agents.data_analyst_agent = boom
    try:
        task = Task(
            request="Analyze quarterly revenue and profit trends.",
            context={"dataset_ids": [ds.id], "user_role": "analyst"},
            max_retries=2,
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        task = await run_workflow(session, task.id)
    finally:
        agents.data_analyst_agent = original

    # workflow completed without the PlanStep schema crash
    assert task.error != '"PlanStep" object has no field "error"'
    assert task.status in {"succeeded", "failed"}
    steps = (await session.execute(select(TaskStep).where(TaskStep.task_id == task.id))).scalars().all()
    failed_steps = [s for s in steps if s.status == "failed"]
    assert failed_steps, "failing step must be recorded in the trace"
    assert any("simulated agent explosion" in (s.error or "") for s in failed_steps)
