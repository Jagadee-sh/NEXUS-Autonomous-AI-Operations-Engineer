"""HTTP-based providers: OpenAI, Anthropic, Gemini, Ollama."""

from __future__ import annotations

import json

import httpx

from nexus.config import settings
from nexus.core.exceptions import ProviderError
from nexus.llm.base import LLMMessage, LLMProvider, LLMResponse


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, model: str | None = None, api_key: str | None = None):
        self.model = model or settings.openai_model
        self.api_key = api_key or settings.openai_api_key

    def healthy(self) -> bool:
        return bool(self.api_key)

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        timeout: float = 60.0,
    ) -> LLMResponse:
        if not self.api_key:
            raise ProviderError("OpenAI API key not configured")
        payload = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
        if resp.status_code >= 400:
            raise ProviderError(f"OpenAI error {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        choice = data["choices"][0]["message"]["content"] or ""
        usage = data.get("usage", {})
        return LLMResponse(
            content=choice,
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
            estimated_cost=_openai_cost(self.model, usage),
            model=self.model,
            raw={"id": data.get("id")},
        )


def _openai_cost(model: str, usage: dict) -> float:
    pin, pout = 0.15 / 1e6, 0.60 / 1e6
    if "gpt-4o" == model:
        pin, pout = 2.5 / 1e6, 10.0 / 1e6
    return round((usage.get("prompt_tokens", 0) * pin + usage.get("completion_tokens", 0) * pout), 6)


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, model: str | None = None, api_key: str | None = None):
        self.model = model or settings.anthropic_model
        self.api_key = api_key or settings.anthropic_api_key

    def healthy(self) -> bool:
        return bool(self.api_key)

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        timeout: float = 60.0,
    ) -> LLMResponse:
        if not self.api_key:
            raise ProviderError("Anthropic API key not configured")
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        chat = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
        payload = {
            "model": self.model,
            "system": system or None,
            "messages": chat,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
            )
        if resp.status_code >= 400:
            raise ProviderError(f"Anthropic error {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        usage = data.get("usage", {})
        return LLMResponse(
            content=text,
            tokens_in=usage.get("input_tokens", 0),
            tokens_out=usage.get("output_tokens", 0),
            estimated_cost=round(usage.get("input_tokens", 0) * 3e-6 + usage.get("output_tokens", 0) * 15e-6, 6),
            model=self.model,
        )


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, model: str | None = None, api_key: str | None = None):
        self.model = model or settings.google_model
        self.api_key = api_key or settings.google_api_key

    def healthy(self) -> bool:
        return bool(self.api_key)

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        timeout: float = 60.0,
    ) -> LLMResponse:
        if not self.api_key:
            raise ProviderError("Google API key not configured")
        system = "\n".join(m.content for m in messages if m.role == "system")
        contents = [
            {"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
            for m in messages
            if m.role != "system"
        ]
        payload = {
            "contents": contents,
            "systemInstruction": {"parts": [{"text": system}]} if system else None,
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, params={"key": self.api_key}, json=payload)
        if resp.status_code >= 400:
            raise ProviderError(f"Gemini error {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            text = json.dumps(data)[:500]
        usage = data.get("usageMetadata", {})
        return LLMResponse(
            content=text,
            tokens_in=usage.get("promptTokenCount", 0),
            tokens_out=usage.get("candidatesTokenCount", 0),
            estimated_cost=0.0,
            model=self.model,
        )


class GroqProvider(LLMProvider):
    """Groq-hosted Llama models via the OpenAI-compatible chat completions API."""

    name = "groq"
    BASE_URL = "https://api.groq.com/openai/v1"

    def __init__(self, model: str | None = None, api_key: str | None = None):
        self.model = model or settings.groq_model
        self.api_key = api_key or settings.groq_api_key

    def healthy(self) -> bool:
        return bool(self.api_key)

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        timeout: float = 60.0,
    ) -> LLMResponse:
        if not self.api_key:
            raise ProviderError("Groq API key not configured")
        payload = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        import asyncio

        resp = None
        last_text = ""
        for attempt in range(4):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(
                        f"{self.BASE_URL}/chat/completions",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json=payload,
                    )
            except httpx.HTTPError as exc:
                if attempt == 3:
                    raise ProviderError(f"Groq unreachable: {exc}") from exc
                await asyncio.sleep(2.0 * (attempt + 1))
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                last_text = resp.text[:300]
                if attempt == 3:
                    break
                # free-tier TPM windows are short — back off far enough to cross them
                await asyncio.sleep((2.0, 5.0, 10.0)[attempt])
                continue
            break
        if resp is None or resp.status_code >= 400:
            detail = last_text or (resp.text[:300] if resp else "unreachable")
            code = resp.status_code if resp else "n/a"
            raise ProviderError(f"Groq error {code}: {detail}")
        data = resp.json()
        choice = data["choices"][0]["message"]["content"] or ""
        usage = data.get("usage", {})
        pin, pout = 0.59 / 1e6, 0.79 / 1e6  # llama-3.3-70b pricing (approx)
        return LLMResponse(
            content=choice,
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
            estimated_cost=round(
                usage.get("prompt_tokens", 0) * pin + usage.get("completion_tokens", 0) * pout, 6
            ),
            model=self.model,
            raw={"id": data.get("id")},
        )


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, model: str | None = None, base_url: str | None = None):
        self.model = model or settings.ollama_model
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")

    def healthy(self) -> bool:
        return True  # checked lazily

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        timeout: float = 120.0,
    ) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(f"{self.base_url}/api/chat", json=payload)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Ollama unreachable: {exc}") from exc
        if resp.status_code >= 400:
            raise ProviderError(f"Ollama error {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        return LLMResponse(
            content=data.get("message", {}).get("content", ""),
            tokens_in=data.get("prompt_eval_count", 0),
            tokens_out=data.get("eval_count", 0),
            model=self.model,
        )
