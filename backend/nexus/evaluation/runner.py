"""Evaluation framework: datasets, metrics, runner."""

from __future__ import annotations

import re
import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.database.base import utcnow
from nexus.database.models import EvaluationDataset, EvaluationRun, Metric, Task
from nexus.logging_config import get_logger
from nexus.orchestration.engine import run_workflow

log = get_logger("nexus.evaluation")

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall((text or "").lower()) if len(t) > 2}


def keyword_recall(expected: str, actual: str) -> float:
    e, a = _tokens(expected), _tokens(actual)
    if not e:
        return 0.0
    return round(len(e & a) / len(e), 4)


def groundedness(answer: str, evidence_texts: list[str]) -> float:
    a = _tokens(answer)
    if not a:
        return 0.0
    corpus = _tokens(" ".join(evidence_texts))
    if not corpus:
        return 0.0
    return round(len(a & corpus) / len(a), 4)


def retrieval_relevance(expected_sources: list[str], retrieved_sources: list[str]) -> float:
    if not expected_sources:
        return 1.0
    got = [s.lower() for s in retrieved_sources]
    matched = sum(1 for e in expected_sources if any(e.lower() in g for g in got))
    return round(matched / len(expected_sources), 4)


async def run_evaluation(session: AsyncSession, dataset_id: str) -> EvaluationRun:
    dataset = await session.get(EvaluationDataset, dataset_id)
    if not dataset:
        raise ValueError("Evaluation dataset not found")

    run = EvaluationRun(dataset_id=dataset_id, status="running", started_at=utcnow())
    session.add(run)
    await session.commit()
    await session.refresh(run)

    items: list[dict[str, Any]] = list(dataset.items or [])
    results: list[dict[str, Any]] = []
    totals = {
        "answer_correctness": [],
        "faithfulness": [],
        "retrieval_relevance": [],
        "task_success_rate": [],
        "correction_success_rate": [],
        "latency_seconds": [],
    }

    for item in items:
        question = item.get("question", "")
        expected_answer = item.get("expected_answer", "")
        expected_sources = item.get("expected_sources", [])
        started = time.perf_counter()
        task = Task(request=question, title=f"eval:{item.get('id', question[:40])}", max_retries=3, context={})
        session.add(task)
        await session.commit()
        await session.refresh(task)
        try:
            task = await run_workflow(session, task.id)
            latency = time.perf_counter() - started
            answer = (task.result or {}).get("answer", "") or ""
            citations = (task.result or {}).get("citations", []) or []
            corrections = (task.result or {}).get("corrections", []) or []
            evidence_items = (task.result or {}).get("summary", {}).get("evidence", []) or []
            evidence_texts = [
                (e.get("excerpt") if isinstance(e, dict) else getattr(e, "excerpt", ""))
                for e in evidence_items
            ]
            # data analysis outputs also ground claims
            for finding in ((task.result or {}).get("findings") or [])[:8]:
                if isinstance(finding, dict):
                    evidence_texts.append(str(finding.get("detail", "")))
            evidence_texts = [e for e in evidence_texts if e] or [answer[:500]]
            item_metrics = {
                "id": item.get("id"),
                "task_id": task.id,
                "status": task.status,
                "answer_correctness": keyword_recall(expected_answer, answer) if expected_answer else None,
                "faithfulness": groundedness(answer, evidence_texts),
                "retrieval_relevance": retrieval_relevance(expected_sources, citations),
                "corrections": len(corrections),
                "latency_seconds": round(latency, 3),
                "confidence": task.confidence,
            }
            if item_metrics["answer_correctness"] is not None:
                totals["answer_correctness"].append(item_metrics["answer_correctness"])
            totals["faithfulness"].append(item_metrics["faithfulness"])
            totals["retrieval_relevance"].append(item_metrics["retrieval_relevance"])
            totals["task_success_rate"].append(1.0 if task.status == "succeeded" else 0.0)
            if corrections:
                totals["correction_success_rate"].append(1.0 if task.status == "succeeded" else 0.0)
            totals["latency_seconds"].append(item_metrics["latency_seconds"])
            results.append(item_metrics)
        except Exception as exc:  # noqa: BLE001
            log.exception("evaluation item failed")
            results.append({"id": item.get("id"), "status": "error", "error": str(exc)[:500]})
            totals["task_success_rate"].append(0.0)

    def _avg(vals: list[float]) -> float:
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    metrics = {k: _avg(v) for k, v in totals.items()}
    run.metrics = metrics
    run.results = results
    run.status = "succeeded"
    run.finished_at = utcnow()
    for name, value in metrics.items():
        session.add(Metric(run_id=run.id, name=name, value=value))
    await session.commit()
    await session.refresh(run)
    return run
