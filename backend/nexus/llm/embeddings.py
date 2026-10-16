"""Embedding providers: deterministic local hash embeddings + OpenAI."""

from __future__ import annotations

import hashlib
import math
import re

import httpx

from nexus.config import settings
from nexus.core.exceptions import ProviderError
from nexus.llm.base import EmbeddingProvider

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _hash_token(token: str, dim: int) -> int:
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % dim


class LocalEmbeddingProvider(EmbeddingProvider):
    """Signed hashing bag-of-words embeddings. Deterministic, offline, no training.

    Quality is sufficient for keyword-adjacent semantic overlap in demos/tests;
    production should use a real embedding model via OpenAI/Ollama.
    """

    name = "local"

    def __init__(self, dim: int | None = None):
        self.dim = dim or settings.embedding_dim

    def healthy(self) -> bool:
        return True

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = _TOKEN_RE.findall(text.lower())
        if not tokens:
            return vec
        for tok in tokens:
            idx = _hash_token(tok, self.dim)
            sign = 1.0 if _hash_token(tok + "#sign", 2) == 0 else -1.0
            # sublinear tf via log1p handled by counting first
            vec[idx] += sign
        # light normalization
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text)


class OpenAIEmbeddingProvider(EmbeddingProvider):
    name = "openai"

    def __init__(self, model: str | None = None, api_key: str | None = None, dim: int | None = None):
        self.model = model or settings.openai_embedding_model
        self.api_key = api_key or settings.openai_api_key
        self.dim = dim or settings.embedding_dim

    def healthy(self) -> bool:
        return bool(self.api_key)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.api_key:
            raise ProviderError("OpenAI API key not configured for embeddings")
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "input": texts},
            )
        if resp.status_code >= 400:
            raise ProviderError(f"OpenAI embeddings error {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        vectors = [d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"])]
        if vectors:
            self.dim = len(vectors[0])
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed([text]))[0]


class OllamaEmbeddingProvider(EmbeddingProvider):
    name = "ollama"

    def __init__(self, model: str = "nomic-embed-text", base_url: str | None = None, dim: int | None = None):
        self.model = model
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.dim = dim or settings.embedding_dim

    def healthy(self) -> bool:
        return True

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        async with httpx.AsyncClient(timeout=60.0) as client:
            for t in texts:
                resp = await client.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": self.model, "prompt": t},
                )
                if resp.status_code >= 400:
                    raise ProviderError(f"Ollama embedding error {resp.status_code}")
                vec = resp.json().get("embedding", [])
                if vec:
                    self.dim = len(vec)
                out.append(vec)
        return out

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed([text]))[0]
