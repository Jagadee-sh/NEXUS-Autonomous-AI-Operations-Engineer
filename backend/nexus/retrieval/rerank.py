"""Lightweight lexical reranker (token-overlap)."""

from __future__ import annotations

from nexus.llm.base import RerankerProvider
from nexus.retrieval.keyword_index import tokenize


class LexicalReranker(RerankerProvider):
    name = "lexical"

    async def rerank(self, query: str, documents: list[str], top_k: int) -> list[int]:
        q = set(tokenize(query))
        scored: list[tuple[int, float]] = []
        for i, doc in enumerate(documents):
            d = set(tokenize(doc))
            overlap = len(q & d) / max(1, len(q | d))
            scored.append((i, overlap))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [i for i, _ in scored[:top_k]]
