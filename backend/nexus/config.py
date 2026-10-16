"""Centralized configuration for NEXUS."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Core
    nexus_env: str = "development"
    nexus_secret_key: str = "dev-insecure-secret-change-me"
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"
    version: str = "0.1.0"

    # Storage
    database_url: str = f"sqlite+aiosqlite:///{BASE_DIR / 'nexus_storage' / 'nexus.db'}"
    redis_url: str = ""

    # Providers
    llm_provider: str = "local"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"
    google_api_key: str = ""
    google_model: str = "gemini-2.0-flash"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"

    embedding_provider: str = "local"
    openai_embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 256

    vector_store: str = "memory"  # memory | pgvector
    pgvector_url: str = ""

    # Agent runtime
    max_agent_iterations: int = 8
    max_retries: int = 3
    agent_step_timeout_seconds: int = 120
    task_timeout_seconds: int = 600

    # SQL
    sql_timeout_seconds: int = 20
    sql_max_rows: int = 500

    # Sandbox
    sandbox_timeout_seconds: int = 15
    sandbox_memory_mb: int = 256

    # Ingestion
    max_file_size_mb: int = 25
    chunk_size: int = 1000
    chunk_overlap: int = 150
    storage_dir: str = str(BASE_DIR / "nexus_storage")

    # Security
    rate_limit_per_minute: int = 60
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
    api_keys: str = ""
    access_token_expire_minutes: int = 720

    # Tools
    http_tool_allowlist: str = "localhost,127.0.0.1"

    # Observability
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = ""
    otel_exporter_otlp_endpoint: str = ""

    # Worker
    worker_poll_interval: float = 0.25

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def api_key_list(self) -> list[str]:
        return [k.strip() for k in self.api_keys.split(",") if k.strip()]

    @property
    def http_allowlist(self) -> list[str]:
        return [h.strip().lower() for h in self.http_tool_allowlist.split(",") if h.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def storage_path(self) -> Path:
        p = Path(self.storage_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
