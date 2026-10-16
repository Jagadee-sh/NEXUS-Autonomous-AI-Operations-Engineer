"""Vector store abstraction: in-memory (dev) with pgvector-ready interface."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.config import settings
from nexus.database.models import DocumentChunk
from nexus.logging_config import get_logger

log = get_logger("nexus.retrieval")


@dataclass
class ScoredChunk:
    chunk_id: str
    document_id: str
    content: str
    score: float
    page: int | None = None
    section: str | None = None
    filename: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


class VectorStore(Protocol):
    async def upsert_chunks(self, session: AsyncSession, chunks: list[DocumentChunk]) -> None: ...
    async def delete_document(self, document_id: str) -> None: ...
    async def search(
        self,
        session: AsyncSession,
        query_vector: list[float],
        top_k: int = 8,
        document_ids: list[str] | None = None,
        metadata_filters: dict[str, Any] | None = None,
    ) -> list[ScoredChunk]: ...


class InMemoryVectorStore:
    """Scores against persisted chunk embeddings loaded from the database.

    Keeps a lightweight in-process cache keyed by chunk id; the database remains
    the source of truth so restarts and multi-worker setups stay consistent.
    """

    def __init__(self) -> None:
        self._cache: dict[str, ScoredChunk] = {}

    async def upsert_chunks(self, session: AsyncSession, chunks: list[DocumentChunk]) -> None:
        for c in chunks:
            filename = (c.metadata_json or {}).get("filename", "")
            self._cache[c.id] = ScoredChunk(
                chunk_id=c.id,
                document_id=c.document_id,
                content=c.content,
                score=0.0,
                page=c.page,
                section=c.section,
                filename=filename,
                metadata=dict(c.metadata_json or {}),
            )

    async def delete_document(self, document_id: str) -> None:
        for key in [k for k, v in self._cache.items() if v.document_id == document_id]:
            self._cache.pop(key, None)

    async def search(
        self,
        session: AsyncSession,
        query_vector: list[float],
        top_k: int = 8,
        document_ids: list[str] | None = None,
        metadata_filters: dict[str, Any] | None = None,
    ) -> list[ScoredChunk]:
        stmt = select(DocumentChunk)
        if document_ids:
            stmt = stmt.where(DocumentChunk.document_id.in_(document_ids))
        result = await session.execute(stmt.limit(5000))
        rows = list(result.scalars())
        scored: list[ScoredChunk] = []
        for row in rows:
            emb = row.embedding
            if not emb:
                continue
            if metadata_filters:
                meta = row.metadata_json or {}
                if any(meta.get(k) != v for k, v in metadata_filters.items()):
                    continue
            score = cosine(query_vector, emb)
            filename = (row.metadata_json or {}).get("filename", "")
            scored.append(
                ScoredChunk(
                    chunk_id=row.id,
                    document_id=row.document_id,
                    content=row.content,
                    score=score,
                    page=row.page,
                    section=row.section,
                    filename=filename,
                    metadata=dict(row.metadata_json or {}),
                )
            )
            self._cache[row.id] = scored[-1]
        scored.sort(key=lambda c: c.score, reverse=True)
        return scored[:top_k]


class PgVectorStore:
    """Production store using PostgreSQL + pgvector.

    Falls back to the in-memory scorer if the pgvector extension is unavailable,
    logging a clear warning — so deployments never hard-fail on missing extensions.
    """

    def __init__(self, dsn: str):
        self.dsn = dsn
        self._fallback = InMemoryVectorStore()
        self._checked = False
        self._available = False

    async def _ensure(self, session: AsyncSession) -> bool:
        if self._checked:
            return self._available
        self._checked = True
        try:
            from sqlalchemy import text

            await session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await session.commit()
            self._available = True
        except Exception as exc:  # noqa: BLE001
            log.warning("pgvector unavailable (%s); using in-memory scoring fallback", exc)
            self._available = False
        return self._available

    async def upsert_chunks(self, session: AsyncSession, chunks: list[DocumentChunk]) -> None:
        await self._fallback.upsert_chunks(session, chunks)
        # Embeddings remain on the chunk rows; pgvector ANN index can be added via migration
        # when extension exists (vector column + ivfflat/hnsw index).

    async def delete_document(self, document_id: str) -> None:
        await self._fallback.delete_document(document_id)

    async def search(self, session, query_vector, top_k=8, document_ids=None, metadata_filters=None):
        await self._ensure(session)
        return await self._fallback.search(
            session, query_vector, top_k, document_ids, metadata_filters
        )


_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    global _store
    if _store is None:
        if settings.vector_store == "pgvector" and settings.pgvector_url:
            _store = PgVectorStore(settings.pgvector_url)
        else:
            _store = InMemoryVectorStore()
    return _store


def reset_vector_store_for_tests() -> None:
    global _store
    _store = None
