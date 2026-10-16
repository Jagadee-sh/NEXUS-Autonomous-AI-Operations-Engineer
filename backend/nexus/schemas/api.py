"""Pydantic schemas for the API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str = "analyst"

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class TaskCreate(BaseModel):
    request: str = Field(min_length=3, max_length=20000)
    title: str = Field(default="", max_length=300)
    priority: str = "normal"
    document_ids: list[str] = Field(default_factory=list)
    dataset_ids: list[str] = Field(default_factory=list)
    datasource_id: str | None = None
    max_retries: int | None = Field(default=None, ge=0, le=10)
    # demo hook: {"category": "poor_retrieval", "fail_first": 1}
    failure_injection: dict[str, Any] | None = None


class TaskOut(BaseModel):
    id: str
    title: str
    request: str
    status: str
    priority: str
    trace_id: str
    plan: Any = None
    result: dict[str, Any] | None = None
    confidence: float | None = None
    error: str | None = None
    retry_count: int
    max_retries: int
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    model_config = {"from_attributes": True}


class QueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=20000)
    document_ids: list[str] = Field(default_factory=list)
    dataset_ids: list[str] = Field(default_factory=list)
    datasource_id: str | None = None
    wait: bool = True
    failure_injection: dict[str, Any] | None = None


class DocumentOut(BaseModel):
    id: str
    filename: str
    content_type: str
    size_bytes: int
    status: str
    error: str | None = None
    chunk_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class DatasetOut(BaseModel):
    id: str
    name: str
    filename: str
    status: str
    error: str | None = None
    row_count: int
    columns_json: list[Any]
    stats_json: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class DataSourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(default="sqlite", pattern="^(sqlite|postgres)$")
    connection_url: str = Field(min_length=5, max_length=1000)


class DataSourceOut(BaseModel):
    id: str
    name: str
    kind: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ApprovalDecision(BaseModel):
    reason: str = Field(default="", max_length=2000)


class ApprovalOut(BaseModel):
    id: str
    task_id: str | None
    action: str
    risk_level: str
    payload: dict[str, Any]
    status: str
    requested_by: str
    decided_by: str | None
    decided_at: datetime | None
    reason: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class EvalDatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    description: str = ""
    items: list[dict[str, Any]] = Field(default_factory=list)


class EvalDatasetOut(BaseModel):
    id: str
    name: str
    description: str
    items: list[Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class EvalRunCreate(BaseModel):
    dataset_id: str


class ResearchCreate(BaseModel):
    dataset_id: str | None = None
    questions: list[str] = Field(default_factory=list)
    top_k: int = Field(default=6, ge=1, le=20)


class EvalRunOut(BaseModel):
    id: str
    dataset_id: str
    status: str
    metrics: dict[str, Any]
    results: list[Any]
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class HealthOut(BaseModel):
    status: str
    version: str
    time: datetime
