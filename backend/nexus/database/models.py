"""Relational models for NEXUS (see docs/DATA_MODEL.md)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nexus.database.base import Base, TimestampMixin, UUIDPkMixin, utcnow


class Role(Base, UUIDPkMixin, TimestampMixin):
    __tablename__ = "roles"
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    permissions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Organization(Base, UUIDPkMixin, TimestampMixin):
    __tablename__ = "organizations"
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class User(Base, UUIDPkMixin, TimestampMixin):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(200), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), default="")
    role_id: Mapped[str | None] = mapped_column(ForeignKey("roles.id"), nullable=True)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    role: Mapped[Role | None] = relationship()


class Document(Base, UUIDPkMixin, TimestampMixin):
    __tablename__ = "documents"
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="uploaded", index=True)  # uploaded|processing|ready|failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(30), default="upload")
    storage_path: Mapped[str] = mapped_column(String(1000), default="")
    uploaded_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    chunks: Mapped[list[DocumentChunk]] = relationship(back_populates="document", cascade="all, delete-orphan")


class DocumentChunk(Base, UUIDPkMixin, TimestampMixin):
    __tablename__ = "document_chunks"
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section: Mapped[str | None] = mapped_column(String(300), nullable=True)
    token_estimate: Mapped[int] = mapped_column(Integer, default=0)
    embedding: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)  # memory store; pgvector in prod
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    document: Mapped[Document] = relationship(back_populates="chunks")


class DataSource(Base, UUIDPkMixin, TimestampMixin):
    __tablename__ = "data_sources"
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), default="sqlite")  # sqlite|postgres
    connection_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="unknown")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Dataset(Base, UUIDPkMixin, TimestampMixin):
    __tablename__ = "datasets"
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    filename: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(30), default="uploaded", index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_path: Mapped[str] = mapped_column(String(1000), default="")
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    columns_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    stats_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Agent(Base, UUIDPkMixin, TimestampMixin):
    __tablename__ = "agents"
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    tools: Mapped[list[Any]] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Task(Base, UUIDPkMixin, TimestampMixin):
    __tablename__ = "tasks"
    title: Mapped[str] = mapped_column(String(300), default="")
    request: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    trace_id: Mapped[str] = mapped_column(String(36), unique=True, index=True, default="")
    plan: Mapped[list[Any] | dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    steps: Mapped[list[TaskStep]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="TaskStep.sequence"
    )


Index("ix_tasks_status_created", Task.status, Task.created_at)


class TaskStep(Base, UUIDPkMixin, TimestampMixin):
    __tablename__ = "task_steps"
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    agent: Mapped[str] = mapped_column(String(80), default="")
    step_type: Mapped[str] = mapped_column(String(40), default="")  # plan|retrieve|analyze|sql|tool|validate|correct|report
    status: Mapped[str] = mapped_column(String(30), default="running")
    input: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)

    task: Mapped[Task] = relationship(back_populates="steps")


class AgentExecution(Base, UUIDPkMixin, TimestampMixin):
    __tablename__ = "agent_executions"
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    agent: Mapped[str] = mapped_column(String(80), nullable=False)
    iteration: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="running")
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Message(Base, UUIDPkMixin, TimestampMixin):
    __tablename__ = "messages"
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user|assistant|system
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class RetrievalResult(Base, UUIDPkMixin, TimestampMixin):
    __tablename__ = "retrieval_results"
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True, index=True)
    query: Mapped[str] = mapped_column(Text, default="")
    strategy: Mapped[str] = mapped_column(String(40), default="hybrid")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    chunk_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    document_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    content_snippet: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Evidence(Base, UUIDPkMixin, TimestampMixin):
    __tablename__ = "evidence"
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    claim: Mapped[str] = mapped_column(Text, default="")
    source_ref: Mapped[str] = mapped_column(String(500), default="")
    excerpt: Mapped[str] = mapped_column(Text, default="")
    strength: Mapped[float] = mapped_column(Float, default=0.0)


class ValidationResult(Base, UUIDPkMixin, TimestampMixin):
    __tablename__ = "validation_results"
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    issues: Mapped[list[Any]] = mapped_column(JSON, default=list)
    unsupported_claims: Mapped[list[Any]] = mapped_column(JSON, default=list)


class CorrectionAttempt(Base, UUIDPkMixin, TimestampMixin):
    __tablename__ = "correction_attempts"
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    failure_category: Mapped[str] = mapped_column(String(60), default="")
    strategy: Mapped[str] = mapped_column(String(60), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    succeeded: Mapped[bool] = mapped_column(Boolean, default=False)


class Tool(Base, UUIDPkMixin, TimestampMixin):
    __tablename__ = "tools"
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    permission_level: Mapped[str] = mapped_column(String(20), default="LOW")  # LOW|MEDIUM|HIGH|CRITICAL
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ToolExecution(Base, UUIDPkMixin, TimestampMixin):
    __tablename__ = "tool_executions"
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True, index=True)
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False)
    agent: Mapped[str] = mapped_column(String(80), default="")
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_summary: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="success")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    risk_level: Mapped[str] = mapped_column(String(20), default="LOW")


class ApprovalRequest(Base, UUIDPkMixin, TimestampMixin):
    __tablename__ = "approval_requests"
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(300), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), default="HIGH")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # pending|approved|rejected
    requested_by: Mapped[str] = mapped_column(String(100), default="system")
    decided_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditLog(Base, UUIDPkMixin, TimestampMixin):
    __tablename__ = "audit_logs"
    actor: Mapped[str] = mapped_column(String(120), default="system")
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), default="")
    resource_id: Mapped[str] = mapped_column(String(80), default="")
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ip: Mapped[str | None] = mapped_column(String(60), nullable=True)


Index("ix_audit_created", AuditLog.created_at)


class EvaluationDataset(Base, UUIDPkMixin, TimestampMixin):
    __tablename__ = "evaluation_datasets"
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    items: Mapped[list[Any]] = mapped_column(JSON, default=list)


class EvaluationRun(Base, UUIDPkMixin, TimestampMixin):
    __tablename__ = "evaluation_runs"
    dataset_id: Mapped[str] = mapped_column(ForeignKey("evaluation_datasets.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="running", index=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    results: Mapped[list[Any]] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Metric(Base, UUIDPkMixin, TimestampMixin):
    __tablename__ = "metrics"
    run_id: Mapped[str] = mapped_column(ForeignKey("evaluation_runs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    value: Mapped[float] = mapped_column(Float, default=0.0)
    slice: Mapped[str] = mapped_column(String(120), default="")
