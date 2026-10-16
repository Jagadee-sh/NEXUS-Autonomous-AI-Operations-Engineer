"""Ingestion pipeline: upload → validate → extract → chunk → embed → index."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.config import settings
from nexus.core.exceptions import NotFoundError
from nexus.database.models import Document, DocumentChunk
from nexus.ingestion.chunker import chunk_segments
from nexus.ingestion.extractors import extract_file, validate_upload
from nexus.llm.registry import get_embedding_provider
from nexus.logging_config import get_logger
from nexus.retrieval.vector_store import get_vector_store

log = get_logger("nexus.ingestion")

CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


async def ingest_document(
    session: AsyncSession,
    *,
    filename: str,
    content: bytes,
    content_type: str | None = None,
    uploaded_by: str | None = None,
) -> Document:
    ext = Path(filename).suffix.lower()
    ctype = content_type or CONTENT_TYPES.get(ext, "application/octet-stream")
    validate_upload(filename, ctype, len(content), settings.max_file_size_mb)

    doc_id = str(uuid.uuid4())
    dest_dir = settings.storage_path / "documents" / doc_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name
    dest = dest_dir / safe_name
    dest.write_bytes(content)

    doc = Document(
        id=doc_id,
        filename=safe_name,
        content_type=ctype,
        size_bytes=len(content),
        status="processing",
        uploaded_by=uploaded_by,
        storage_path=str(dest),
    )
    session.add(doc)
    await session.commit()
    await session.refresh(doc)

    try:
        segments = extract_file(dest, safe_name)
        chunks = chunk_segments(segments, settings.chunk_size, settings.chunk_overlap)
        embedder = get_embedding_provider()
        texts = [c.content for c in chunks]
        embeddings = await embedder.embed(texts) if texts else []

        store = get_vector_store()
        rows: list[DocumentChunk] = []
        for _i, (chunk, emb) in enumerate(zip(chunks, embeddings, strict=False)):
            row = DocumentChunk(
                document_id=doc_id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                page=chunk.page,
                section=chunk.section,
                token_estimate=chunk.token_estimate,
                embedding=emb,
                metadata_json={
                    "document_id": doc_id,
                    "filename": safe_name,
                    "page": chunk.page,
                    "section": chunk.section,
                    **(chunk.metadata or {}),
                },
            )
            session.add(row)
            rows.append(row)
        doc.status = "ready"
        doc.chunk_count = len(rows)
        doc.error = None
        await session.commit()
        await session.refresh(doc)

        await store.upsert_chunks(session, rows)
        log.info("ingested document %s (%d chunks)", safe_name, len(rows))
        return doc
    except Exception as exc:  # noqa: BLE001 - persist failure status
        doc.status = "failed"
        doc.error = str(exc)[:2000]
        await session.commit()
        await session.refresh(doc)
        log.exception("ingestion failed for %s", safe_name)
        raise


async def delete_document(session: AsyncSession, document_id: str) -> None:
    doc = await session.get(Document, document_id)
    if not doc:
        raise NotFoundError("Document not found")
    store = get_vector_store()
    await store.delete_document(document_id)
    await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
    await session.delete(doc)
    await session.commit()
    if doc.storage_path:
        p = Path(doc.storage_path).parent
        if p.exists() and settings.storage_path in p.parents:
            shutil.rmtree(p, ignore_errors=True)


async def list_documents(session: AsyncSession, limit: int = 100, offset: int = 0) -> list[Document]:
    result = await session.execute(
        select(Document).order_by(Document.created_at.desc()).limit(limit).offset(offset)
    )
    return list(result.scalars())
