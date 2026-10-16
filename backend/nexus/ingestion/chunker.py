"""Chunking with overlap, preserving page/section metadata."""

from __future__ import annotations

from dataclasses import dataclass

from nexus.ingestion.extractors import ExtractedSegment


@dataclass
class Chunk:
    content: str
    chunk_index: int
    page: int | None = None
    section: str | None = None
    token_estimate: int = 0
    metadata: dict | None = None


def _split_paragraphs(text: str) -> list[str]:
    parts = [p.strip() for p in text.split("\n")]
    return [p for p in parts if p]


def chunk_segments(
    segments: list[ExtractedSegment],
    chunk_size: int = 1000,
    overlap: int = 150,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    idx = 0
    for seg in segments:
        paragraphs = _split_paragraphs(seg.text)
        current = ""
        for para in paragraphs:
            candidate = f"{current}\n{para}".strip() if current else para
            if len(candidate) <= chunk_size:
                current = candidate
                continue
            if current:
                chunks.append(
                    Chunk(
                        content=current,
                        chunk_index=idx,
                        page=seg.page,
                        section=seg.section,
                        token_estimate=len(current) // 4,
                        metadata=dict(seg.metadata or {}),
                    )
                )
                idx += 1
                current = current[-overlap:] if overlap else ""
            # hard-split very long paragraph
            while len(para) > chunk_size:
                piece = para[:chunk_size]
                chunks.append(
                    Chunk(
                        content=piece,
                        chunk_index=idx,
                        page=seg.page,
                        section=seg.section,
                        token_estimate=len(piece) // 4,
                        metadata=dict(seg.metadata or {}),
                    )
                )
                idx += 1
                para = para[chunk_size - overlap :]
            current = f"{current}\n{para}".strip() if current else para
        if current.strip():
            chunks.append(
                Chunk(
                    content=current,
                    chunk_index=idx,
                    page=seg.page,
                    section=seg.section,
                    token_estimate=len(current) // 4,
                    metadata=dict(seg.metadata or {}),
                )
            )
            idx += 1
    return chunks
