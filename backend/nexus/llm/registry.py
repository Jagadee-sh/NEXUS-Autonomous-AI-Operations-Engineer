"""Provider registry — resolves configured providers with local fallback."""

from __future__ import annotations

from functools import lru_cache

from nexus.config import settings
from nexus.core.exceptions import ProviderError
from nexus.llm.base import EmbeddingProvider, LLMProvider
from nexus.llm.embeddings import (
    LocalEmbeddingProvider,
    OllamaEmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from nexus.llm.http_providers import (
    AnthropicProvider,
    GeminiProvider,
    GroqProvider,
    OllamaProvider,
    OpenAIProvider,
)
from nexus.llm.local_provider import LocalLLMProvider

_LOCAL = LocalLLMProvider()


@lru_cache
def get_llm_provider() -> LLMProvider:
    name = (settings.llm_provider or "local").lower()
    if name == "openai" and settings.openai_api_key:
        return OpenAIProvider()
    if name == "anthropic" and settings.anthropic_api_key:
        return AnthropicProvider()
    if name == "gemini" and settings.google_api_key:
        return GeminiProvider()
    if name == "groq" and settings.groq_api_key:
        return GroqProvider()
    if name == "ollama":
        return OllamaProvider()
    if name == "local":
        return _LOCAL
    # configured but missing credentials → local fallback
    return _LOCAL


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    name = (settings.embedding_provider or "local").lower()
    if name == "openai" and settings.openai_api_key:
        return OpenAIEmbeddingProvider()
    if name == "ollama":
        return OllamaEmbeddingProvider()
    return LocalEmbeddingProvider()


async def llm_complete(prompt_system: str, prompt_user: str, **kwargs) -> object:
    provider = get_llm_provider()
    from nexus.llm.base import LLMMessage

    return await provider.complete(
        [LLMMessage(role="system", content=prompt_system), LLMMessage(role="user", content=prompt_user)],
        **kwargs,
    )


def reset_registry_for_tests() -> None:
    get_llm_provider.cache_clear()
    get_embedding_provider.cache_clear()


__all__ = [
    "get_llm_provider",
    "get_embedding_provider",
    "llm_complete",
    "reset_registry_for_tests",
    "ProviderError",
]
