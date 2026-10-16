"""Shared pytest fixtures: isolated DB, app client, seeded knowledge."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest_asyncio

TMP = Path(tempfile.mkdtemp(prefix="nexus_test_"))
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TMP / 'test.db'}"
os.environ["NEXUS_ENV"] = "test"
os.environ["LLM_PROVIDER"] = "local"
os.environ["EMBEDDING_PROVIDER"] = "local"
os.environ["VECTOR_STORE"] = "memory"
os.environ["REDIS_URL"] = ""
os.environ["RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["NEXUS_SECRET_KEY"] = "test-secret-key"
os.environ["STORAGE_DIR"] = str(TMP / "storage")

from nexus.config import get_settings  # noqa: E402

get_settings.cache_clear()

from nexus.database.base import Base  # noqa: E402
from nexus.database.session import get_engine, get_session_factory, init_db, reset_engine_for_tests  # noqa: E402
from nexus.llm.registry import reset_registry_for_tests  # noqa: E402
from nexus.retrieval.keyword_index import reset_bm25_for_tests  # noqa: E402
from nexus.retrieval.vector_store import reset_vector_store_for_tests  # noqa: E402
from nexus.workers.queue import reset_queue_for_tests  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def _fresh_db():
    reset_engine_for_tests()
    reset_registry_for_tests()
    reset_bm25_for_tests()
    reset_vector_store_for_tests()
    reset_queue_for_tests()
    get_settings.cache_clear()
    await init_db()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


@pytest_asyncio.fixture
async def session():
    factory = get_session_factory()
    async with factory() as s:
        yield s


@pytest_asyncio.fixture
async def client():
    from httpx import ASGITransport, AsyncClient

    from nexus.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


DEMO_SALES_CSV = b"""date,region,revenue,cogs,operating_expenses,quarter
2024-04-01,North,10000,5800,1200,2
2024-04-15,South,11000,6200,1300,2
2024-05-01,East,12000,6500,1400,2
2024-06-01,West,13000,7000,1500,2
2024-07-01,North,9000,6300,1200,3
2024-07-15,South,9500,6600,1250,3
2024-08-01,East,10000,7000,1300,3
2024-09-01,West,10500,7300,1350,3
"""

POLICY_TXT = b"""Travel Policy Manual

All travel expenses above $2,000 require VP approval before booking.
Monthly cloud spend variance above 15 percent must be reviewed by FinOps.
Critical support tickets require first response within 4 business hours.
Any customer segment with monthly churn above 10 percent triggers a customer success review.
"""
