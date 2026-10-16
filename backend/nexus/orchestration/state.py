"""Workflow state shared across agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    agent: str
    goal: str
    inputs: list[str] = Field(default_factory=list)
    status: str = "pending"  # pending|running|done|failed|skipped
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class Plan(BaseModel):
    summary: str = ""
    steps: list[PlanStep] = Field(default_factory=list)


class RetrievedDoc(BaseModel):
    chunk_id: str
    document_id: str
    filename: str = ""
    page: int | None = None
    section: str | None = None
    content: str
    score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)

    def citation(self) -> str:
        loc = []
        if self.filename:
            loc.append(self.filename)
        if self.page:
            loc.append(f"p.{self.page}")
        if self.section:
            loc.append(self.section)
        return " · ".join(loc) if loc else self.document_id[:8]


class EvidenceItem(BaseModel):
    claim: str
    source_ref: str
    excerpt: str
    strength: float = 0.5


class FindingItem(BaseModel):
    title: str
    detail: str
    metric: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    source_kind: str = "data"  # data|document|both


@dataclass
class WorkflowState:
    task_id: str
    trace_id: str
    request: str
    user_id: str | None = None
    user_role: str = "analyst"
    document_ids: list[str] = field(default_factory=list)
    dataset_ids: list[str] = field(default_factory=list)
    datasource_id: str | None = None

    plan: Plan | None = None
    current_step: str = "start"
    iteration: int = 0
    retry_count: int = 0
    max_retries: int = 3

    retrieved_documents: list[RetrievedDoc] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    sql_results: list[dict[str, Any]] = field(default_factory=list)
    analysis_results: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)
    findings: list[FindingItem] = field(default_factory=list)
    validation_results: list[dict[str, Any]] = field(default_factory=list)
    correction_history: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    final_answer: str | None = None
    confidence: float = 0.0
    limitations: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    # dataset profiles captured at start
    dataset_profiles: dict[str, dict[str, Any]] = field(default_factory=dict)
    dataset_paths: dict[str, str] = field(default_factory=dict)
    datasource_url: str | None = None
    schema: dict[str, list[str]] = field(default_factory=dict)

    metadata: dict[str, Any] = field(default_factory=dict)

    def summary_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "plan": self.plan.model_dump() if self.plan else None,
            "retrieved": len(self.retrieved_documents),
            "findings": [f.model_dump() for f in self.findings],
            "evidence": [e.model_dump() for e in self.evidence],
            "validation": self.validation_results,
            "corrections": self.correction_history,
            "confidence": self.confidence,
            "iterations": self.iteration,
            "retries": self.retry_count,
            "errors": self.errors,
        }
