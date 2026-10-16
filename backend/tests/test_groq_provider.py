"""Groq provider tests (mocked HTTP — no network in CI)."""

from __future__ import annotations

import httpx
import pytest

from nexus.core.exceptions import ProviderError
from nexus.llm.base import LLMMessage
from nexus.llm.http_providers import GroqProvider


class _FakeResp:
    status_code = 200

    def __init__(self, body: dict | None = None, text: str = ""):
        self._body = body or {}
        self.text = text or ""

    def json(self) -> dict:
        return self._body


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, headers=None, json=None):
        assert "api.groq.com" in url
        assert headers["Authorization"].startswith("Bearer ")
        assert json["model"]
        return _FakeResp(
            {
                "id": "chatcmpl-test",
                "choices": [{"message": {"role": "assistant", "content": "NEXUS-OK"}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10},
            }
        )


def test_groq_provider_requires_key():
    p = GroqProvider(model="m", api_key="placeholder")
    p.api_key = ""  # simulate missing credentials regardless of env/.env
    assert p.healthy() is False
    with pytest.raises(ProviderError):
        import asyncio

        asyncio.run(
            p.complete([LLMMessage(role="user", content="hi")])
        )


def test_groq_provider_completes(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    p = GroqProvider(model="test-model", api_key="gsk_test")
    assert p.healthy() is True
    import asyncio

    r = asyncio.run(p.complete([LLMMessage(role="user", content="hi")]))
    assert r.content == "NEXUS-OK"
    assert r.tokens_in == 100 and r.tokens_out == 10
    assert r.estimated_cost > 0
    assert r.model == "test-model"


def test_registry_groq_fallback_without_key(monkeypatch):
    from nexus.config import get_settings
    from nexus.llm.registry import get_llm_provider

    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "")
    get_settings.cache_clear()
    get_llm_provider.cache_clear()
    try:
        p = get_llm_provider()
        assert p.name == "local"  # missing credentials → safe local fallback
    finally:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        get_settings.cache_clear()
        get_llm_provider.cache_clear()
