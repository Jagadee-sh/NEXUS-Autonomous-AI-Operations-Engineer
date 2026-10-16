"""Pure-Python BM25 keyword index (persisted via chunk rows)."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

_TOKEN_RE = re.compile(r"[a-z0-9]+")

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "is", "are", "for", "on", "with",
    "by", "at", "from", "as", "be", "was", "were", "it", "this", "that", "these", "those",
    "we", "our", "their", "its", "into", "than", "then", "so", "if", "but", "not", "no",
}


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]


@dataclass
class BM25Doc:
    doc_id: str
    tokens: list[str]


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._docs: dict[str, list[str]] = {}
        self._doc_len: dict[str, int] = {}
        self._df: Counter[str] = Counter()
        self._avgdl = 0.0

    def add(self, doc_id: str, text: str) -> None:
        tokens = tokenize(text)
        if doc_id in self._docs:
            self.remove(doc_id)
        self._docs[doc_id] = tokens
        self._doc_len[doc_id] = max(1, len(tokens))
        self._df.update(set(tokens))
        self._avgdl = sum(self._doc_len.values()) / max(1, len(self._doc_len))

    def remove(self, doc_id: str) -> None:
        tokens = self._docs.pop(doc_id, None)
        self._doc_len.pop(doc_id, None)
        if tokens:
            for t in set(tokens):
                self._df[t] -= 1
                if self._df[t] <= 0:
                    del self._df[t]

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        q_tokens = tokenize(query)
        if not q_tokens or not self._docs:
            return []
        n = len(self._docs)
        scores: dict[str, float] = {}
        for doc_id, tokens in self._docs.items():
            tf = Counter(tokens)
            dl = self._doc_len[doc_id]
            score = 0.0
            for qt in q_tokens:
                f = tf.get(qt, 0)
                if not f:
                    continue
                df = self._df.get(qt, 0)
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                score += idf * (f * (self.k1 + 1)) / (f + self.k1 * (1 - self.b + self.b * dl / (self._avgdl or 1)))
            if score:
                scores[doc_id] = score
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        return ranked[:top_k]


_index: BM25Index | None = None


def get_bm25_index() -> BM25Index:
    global _index
    if _index is None:
        _index = BM25Index()
    return _index


def reset_bm25_for_tests() -> None:
    global _index
    _index = None
