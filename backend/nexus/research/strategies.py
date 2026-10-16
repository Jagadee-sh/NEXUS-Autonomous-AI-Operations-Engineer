"""Retrieval strategy research: compare vector / keyword / hybrid over eval items.

Runs every question from an evaluation dataset (or ad-hoc questions) through each
retrieval strategy and scores the results with the same metrics used by the
evaluation framework (retrieval_relevance + content keyword recall + hit rate).
Persists the experiment as an EvaluationRun with per-strategy Metric slices.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.database.base import utcnow
from nexus.database.models import EvaluationDataset, EvaluationRun, Metric
from nexus.evaluation.runner import keyword_recall, retrieval_relevance
from nexus.logging_config import get_logger
from nexus.retrieval.hybrid import RetrievalQuery, hybrid_retrieve

log = get_logger("nexus.research")

STRATEGIES = ("vector", "keyword", "hybrid")
RESEARCH_DATASET_NAME = "Research: Retrieval Strategy Comparison"


async def _get_or_create_dataset(session: AsyncSession, dataset_id: str | None) -> EvaluationDataset:
    if dataset_id:
        ds = await session.get(EvaluationDataset, dataset_id)
        if not ds:
            raise ValueError("Evaluation dataset not found")
        return ds
    ds = (
        await session.execute(select(EvaluationDataset).where(EvaluationDataset.name == RESEARCH_DATASET_NAME))
    ).scalars().first()
    if ds:
        return ds
    ds = EvaluationDataset(
        name=RESEARCH_DATASET_NAME,
        description="Ad-hoc questions used by the retrieval-strategy research experiment.",
        items=[],
    )
    session.add(ds)
    await session.commit()
    await session.refresh(ds)
    return ds


async def run_retrieval_comparison(
    session: AsyncSession,
    dataset_id: str | None = None,
    questions: list[str] | None = None,
    top_k: int = 6,
) -> EvaluationRun:
    """Run all strategies × items, aggregate, and persist an EvaluationRun."""
    dataset = await _get_or_create_dataset(session, dataset_id)

    items: list[dict[str, Any]] = list(dataset.items or [])
    if questions:
        for i, q in enumerate(questions):
            items.append({"id": f"adhoc-{i}", "question": q, "expected_sources": [], "expected_answer": ""})
    if not items:
        raise ValueError("No items to research: provide dataset items or questions")

    # persist ad-hoc questions back so the experiment is reproducible
    if questions:
        dataset.items = items
        await session.commit()

    run = EvaluationRun(dataset_id=dataset.id, status="running", started_at=utcnow())
    session.add(run)
    await session.commit()
    await session.refresh(run)

    per_strategy: dict[str, dict[str, list[float]]] = {
        s: {"relevance": [], "content_recall": [], "hit_rate": [], "latency_ms": []} for s in STRATEGIES
    }
    results: list[dict[str, Any]] = []

    for item in items:
        question = item.get("question", "")
        expected_sources = item.get("expected_sources") or []
        expected_answer = item.get("expected_answer") or ""
        item_row: dict[str, Any] = {"id": item.get("id"), "question": question[:160], "strategies": {}}
        for strategy in STRATEGIES:
            started = time.perf_counter()
            try:
                hits = await hybrid_retrieve(
                    session,
                    RetrievalQuery(text=question, strategy=strategy, top_k=top_k, use_rerank=strategy == "hybrid"),
                )
                latency_ms = (time.perf_counter() - started) * 1000
                sources = [h.filename or h.metadata.get("filename", "") or h.document_id[:8] for h in hits]
                contents = [h.content for h in hits]
                relevance = (
                    retrieval_relevance(expected_sources, sources) if expected_sources else None
                )
                content_recall = (
                    keyword_recall(expected_answer, " ".join(contents)) if expected_answer else None
                )
                hit_rate = 1.0 if hits else 0.0
                per_strategy[strategy]["latency_ms"].append(latency_ms)
                per_strategy[strategy]["hit_rate"].append(hit_rate)
                if relevance is not None:
                    per_strategy[strategy]["relevance"].append(relevance)
                if content_recall is not None:
                    per_strategy[strategy]["content_recall"].append(content_recall)
                item_row["strategies"][strategy] = {
                    "hits": len(hits),
                    "relevance": relevance,
                    "content_recall": content_recall,
                    "latency_ms": round(latency_ms, 2),
                    "top_sources": sources[:3],
                }
            except Exception as exc:  # noqa: BLE001
                log.exception("strategy %s failed on item", strategy)
                item_row["strategies"][strategy] = {"error": str(exc)[:300]}
        results.append(item_row)

    def _avg(vals: list[float]) -> float:
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    metrics: dict[str, Any] = {}
    for strategy in STRATEGIES:
        rel = _avg(per_strategy[strategy]["relevance"])
        rec = _avg(per_strategy[strategy]["content_recall"])
        hit = _avg(per_strategy[strategy]["hit_rate"])
        lat = _avg(per_strategy[strategy]["latency_ms"])
        combined = round(0.5 * rel + 0.3 * rec + 0.2 * hit, 4)
        metrics[f"{strategy}_relevance"] = rel
        metrics[f"{strategy}_content_recall"] = rec
        metrics[f"{strategy}_hit_rate"] = hit
        metrics[f"{strategy}_latency_ms"] = lat
        metrics[f"{strategy}_combined"] = combined
        for name, value in (
            ("relevance", rel),
            ("content_recall", rec),
            ("hit_rate", hit),
            ("latency_ms", lat),
            ("combined", combined),
        ):
            session.add(Metric(run_id=run.id, name=name, value=float(value), slice=strategy))

    ranked = sorted(
        STRATEGIES,
        key=lambda s: metrics[f"{s}_combined"],
        reverse=True,
    )
    metrics["best_strategy"] = ranked[0]
    run.metrics = metrics
    run.results = results
    run.status = "succeeded"
    run.finished_at = utcnow()
    await session.commit()
    await session.refresh(run)
    log.info("retrieval strategy research complete: best=%s metrics=%s", ranked[0], metrics)
    return run
