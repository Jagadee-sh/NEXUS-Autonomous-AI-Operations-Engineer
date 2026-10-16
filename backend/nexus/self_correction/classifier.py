"""Failure classification and correction strategies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nexus.logging_config import get_logger
from nexus.orchestration.state import WorkflowState

log = get_logger("nexus.self_correction")

CATEGORIES = [
    "poor_retrieval",
    "missing_evidence",
    "invalid_sql",
    "sql_execution_failure",
    "python_execution_failure",
    "tool_failure",
    "unsupported_claim",
    "insufficient_context",
    "conflicting_evidence",
    "timeout",
]

STRATEGIES = {
    "poor_retrieval": "query_rewrite",
    "missing_evidence": "retrieval_strategy_change",
    "invalid_sql": "sql_regeneration",
    "sql_execution_failure": "sql_regeneration",
    "python_execution_failure": "analysis_regeneration",
    "tool_failure": "tool_retry",
    "unsupported_claim": "query_rewrite",
    "insufficient_context": "plan_modification",
    "conflicting_evidence": "reranking",
    "timeout": "plan_modification",
}


@dataclass
class Diagnosis:
    category: str
    strategy: str
    detail: str
    retry_hint: dict[str, Any]


def classify_failures(state: WorkflowState, validation: dict[str, Any]) -> list[Diagnosis]:
    diagnoses: list[Diagnosis] = []

    for err in state.errors[-5:]:
        low = err.lower()
        if "timed out" in low or "timeout" in low:
            diagnoses.append(Diagnosis("timeout", STRATEGIES["timeout"], err, {"relax_step": True}))
        elif "sql" in low:
            diagnoses.append(Diagnosis("sql_execution_failure", STRATEGIES["sql_execution_failure"], err, {}))
        elif "sandbox" in low or "python" in low:
            diagnoses.append(Diagnosis("python_execution_failure", STRATEGIES["python_execution_failure"], err, {}))
        elif "tool" in low:
            diagnoses.append(Diagnosis("tool_failure", STRATEGIES["tool_failure"], err, {}))

    for step in state.plan.steps if state.plan else []:
        if step.status == "failed":
            if step.agent == "sql_analyst":
                diagnoses.append(
                    Diagnosis("sql_execution_failure", "sql_regeneration", f"SQL step failed: {step.goal}", {})
                )
            elif step.agent == "data_analyst":
                diagnoses.append(
                    Diagnosis("python_execution_failure", "analysis_regeneration", f"Analysis step failed: {step.goal}", {})
                )
            elif step.agent in {"research", "retrieval"}:
                diagnoses.append(
                    Diagnosis("poor_retrieval", "query_rewrite", f"Retrieval step failed: {step.goal}", {})
                )

    if validation:
        if not validation.get("retrieval_ok", True):
            diagnoses.append(
                Diagnosis(
                    "poor_retrieval",
                    "retrieval_strategy_change",
                    "Retrieval produced insufficient results",
                    {"strategy": "keyword", "broaden": True},
                )
            )
        if validation.get("unsupported_claims"):
            diagnoses.append(
                Diagnosis(
                    "unsupported_claim",
                    "query_rewrite",
                    f"{len(validation['unsupported_claims'])} unsupported claim(s)",
                    {"tighten_grounding": True},
                )
            )
        if not validation.get("analysis_ok", True):
            diagnoses.append(
                Diagnosis("python_execution_failure", "analysis_regeneration", "Dataset analysis failed", {})
            )
        if not validation.get("sql_ok", True):
            diagnoses.append(
                Diagnosis("sql_execution_failure", "sql_regeneration", "SQL failed", {})
            )

    # de-dup by category
    seen: set[str] = set()
    unique: list[Diagnosis] = []
    for d in diagnoses:
        if d.category in seen:
            continue
        seen.add(d.category)
        unique.append(d)
    return unique


def build_correction_note(diagnoses: list[Diagnosis], retry_count: int) -> str:
    parts = [f"[retry {retry_count}] Correcting: " + "; ".join(f"{d.category}→{d.strategy}" for d in diagnoses)]
    return " | ".join(parts)
