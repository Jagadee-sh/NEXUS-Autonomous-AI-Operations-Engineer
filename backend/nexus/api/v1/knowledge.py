"""Documents, datasets, datasources."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.api.deps import AuthContext, get_auth_context, require_role
from nexus.core.exceptions import NotFoundError, ValidationError
from nexus.database.models import Dataset, DataSource, Document
from nexus.database.session import get_session
from nexus.execution.sql_engine import async_discover_schema, sanitize_connection_url
from nexus.ingestion.pipeline import delete_document, ingest_document, list_documents
from nexus.schemas.api import DatasetOut, DataSourceCreate, DataSourceOut, DocumentOut
from nexus.services.dataset_service import ingest_dataset

documents_router = APIRouter(prefix="/documents", tags=["documents"])
datasets_router = APIRouter(prefix="/datasets", tags=["datasets"])
datasources_router = APIRouter(prefix="/datasources", tags=["datasources"])


@documents_router.post("", response_model=DocumentOut)
async def upload_document(
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[AuthContext, Depends(require_role("analyst"))],
    file: Annotated[UploadFile, File()],
) -> Document:
    content = await file.read()
    return await ingest_document(
        session,
        filename=file.filename or "upload.bin",
        content=content,
        content_type=file.content_type,
        uploaded_by=ctx.user_id,
    )


@documents_router.get("", response_model=list[DocumentOut])
async def documents(
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    limit: int = Query(default=100, le=500),
    offset: int = 0,
) -> list[Document]:
    return await list_documents(session, limit, offset)


@documents_router.get("/{document_id}", response_model=DocumentOut)
async def document(
    document_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
) -> Document:
    doc = await session.get(Document, document_id)
    if not doc:
        raise NotFoundError("Document not found")
    return doc


@documents_router.delete("/{document_id}")
async def remove_document(
    document_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[AuthContext, Depends(require_role("analyst"))],
) -> dict:
    await delete_document(session, document_id)
    return {"deleted": True, "id": document_id}


@datasets_router.post("", response_model=DatasetOut)
async def upload_dataset(
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[AuthContext, Depends(require_role("analyst"))],
    file: Annotated[UploadFile, File()],
    name: Annotated[str | None, Form()] = None,
) -> Dataset:
    content = await file.read()
    return await ingest_dataset(session, filename=file.filename or "data.csv", content=content, name=name)


@datasets_router.get("", response_model=list[DatasetOut])
async def datasets(
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
) -> list[Dataset]:
    return list((await session.execute(select(Dataset).order_by(Dataset.created_at.desc()))).scalars())


@datasets_router.get("/{dataset_id}", response_model=DatasetOut)
async def dataset(
    dataset_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
) -> Dataset:
    ds = await session.get(Dataset, dataset_id)
    if not ds:
        raise NotFoundError("Dataset not found")
    return ds


@datasources_router.post("", response_model=DataSourceOut)
async def create_datasource(
    body: DataSourceCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[AuthContext, Depends(require_role("analyst"))],
) -> DataSource:
    url = sanitize_connection_url(body.connection_url)
    src = DataSource(name=body.name, kind=body.kind, connection_url=url, status="configured")
    session.add(src)
    await session.commit()
    await session.refresh(src)
    return src


@datasources_router.get("", response_model=list[DataSourceOut])
async def datasources(
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
) -> list[DataSource]:
    return list((await session.execute(select(DataSource).order_by(DataSource.created_at.desc()))).scalars())


@datasources_router.post("/{source_id}/test")
async def test_datasource(
    source_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
) -> dict:
    src = await session.get(DataSource, source_id)
    if not src:
        raise NotFoundError("Data source not found")
    try:
        schema = await async_discover_schema(src.connection_url)
        src.status = "healthy"
        await session.commit()
        return {"ok": True, "tables": list(schema.keys())}
    except Exception as exc:  # noqa: BLE001
        src.status = "error"
        await session.commit()
        return {"ok": False, "error": str(exc)[:500]}


@datasources_router.get("/{source_id}/schema")
async def datasource_schema(
    source_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
) -> dict:
    src = await session.get(DataSource, source_id)
    if not src:
        raise NotFoundError("Data source not found")
    schema = await async_discover_schema(src.connection_url)
    if not schema:
        raise ValidationError("Schema empty or datasource unreachable")
    return {"tables": schema}
