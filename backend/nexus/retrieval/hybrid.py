"""Hybrid retrieval: vector + BM25 fused (RRF), metadata filters, optional rerank."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.database.models import DocumentChunk
from nexus.llm.registry import get_embedding_provider
from nexus.logging_config import get_logger
from nexus.retrieval.keyword_index import get_bm25_index
from nexus.retrieval.rerank import LexicalReranker
from nexus.retrieval.vector_store import ScoredChunk, get_vector_store

log = get_logger("nexus.retrieval.hybrid")

INSTRUCTION_MARKERS = (
    "ignore previous instructions",
    "disregard prior",
    "you are now",
    "system prompt",
    "forget everything",
)


@dataclass
class RetrievalQuery:
    text: str
    document_ids: list[str] | None = None
    metadata_filters: dict[str, Any] | None = None
    top_k: int = 8
    strategy: str = "hybrid"  # hybrid | vector | keyword
    use_rerank: bool = True


def _rrf_fuse(rankings: list[list[tuple[str, float]]], k: int = 60) -> dict[str, float]:
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, (doc_id, _score) in enumerate(ranking, start=1):
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (k + rank)
    return fused


async def ensure_bm25_indexed(session: AsyncSession, document_ids: list[str] | None = None) -> None:
    """Idempotently index chunks into BM25 (keyword index)."""
    index = get_bm25_index()
    stmt = select(DocumentChunk)
    if document_ids:
        stmt = stmt.where(DocumentChunk.document_id.in_(document_ids))
    result = await session.execute(stmt.limit(10000))
    for row in result.scalars():
        index.add(row.id, row.content)


async def hybrid_retrieve(session: AsyncSession, query: RetrievalQuery) -> list[ScoredChunk]:
    top_k = max(1, query.top_k)
    await ensure_bm25_indexed(session, query.document_ids)
    index = get_bm25_index()
    store = get_vector_store()
    embedder = get_embedding_provider()

    vector_hits: list[ScoredChunk] = []
    keyword_hits: list[tuple[str, float]] = []

    if query.strategy in {"hybrid", "vector"}:
        qvec = await embedder.embed_query(query.text)
        vector_hits = await store.search(
            session,
            qvec,
            top_k=top_k * 2,
            document_ids=query.document_ids,
            metadata_filters=query.metadata_filters,
        )
    if query.strategy in {"hybrid", "keyword"}:
        keyword_hits = index.search(query.text, top_k=top_k * 2)

    by_id: dict[str, ScoredChunk] = {c.chunk_id: c for c in vector_hits}

    if query.strategy == "keyword" or query.strategy == "hybrid":
        if keyword_hits:
            ids = [cid for cid, _ in keyword_hits]
            stmt = select(DocumentChunk).where(DocumentChunk.id.in_(ids))
            if query.document_ids:
                stmt = stmt.where(DocumentChunk.document_id.in_(query.document_ids))
            rows = {r.id: r for r in (await session.execute(stmt)).scalars()}
            for cid, score in keyword_hits:
                row = rows.get(cid)
                if not row:
                    continue
                meta = row.metadata_json or {}
                by_id[cid] = ScoredChunk(
                    chunk_id=row.id,
                    document_id=row.document_id,
                    content=row.content,
                    score=float(score),
                    page=row.page,
                    section=row.section,
                    filename=meta.get("filename", ""),
                    metadata=meta,
                )

    if query.strategy == "hybrid":
        rankings: list[list[tuple[str, float]]] = []
        if vector_hits:
            rankings.append([(c.chunk_id, c.score) for c in vector_hits])
        if keyword_hits:
            rankings.append(keyword_hits)
        fused = _rrf_fuse(rankings)
        for cid, fuse_score in fused.items():
            if cid in by_id:
                by_id[cid].score = fuse_score
        results = sorted(by_id.values(), key=lambda c: c.score, reverse=True)[: top_k * 2]
    else:
        results = sorted(by_id.values(), key=lambda c: c.score, reverse=True)[: top_k * 2]

    # drop near-duplicates
    seen: set[str] = set()
    deduped: list[ScoredChunk] = []
    for c in results:
        key = c.content[:160].lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)

    if query.use_rerank and deduped:
        reranker = LexicalReranker()
        order = await reranker.rerank(query.text, [c.content for c in deduped], top_k)
        reranked = [deduped[i] for i in order]
        remaining = [c for i, c in enumerate(deduped) if i not in set(order)]
        deduped = reranked + remaining

    final = deduped[:top_k]
    # annotate prompt-injection suspicion in metadata (defense layer)
    for c in final:
        low = c.content.lower()
        if any(marker in low for marker in INSTRUCTION_MARKERS):
            c.metadata = {**(c.metadata or {}), "suspicious_instructions": True}
    return final
