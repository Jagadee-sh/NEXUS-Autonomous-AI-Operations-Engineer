# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/pyproject.toml backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY backend/nexus ./nexus
RUN pip install --upgrade pip && pip install ".[postgres]"

COPY scripts ./scripts
RUN mkdir -p /app/nexus_storage

EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=5s --start-period=25s --retries=5 \
  CMD curl -fsS http://localhost:8000/health || exit 1

# run migrations on start, then serve (or worker via command override)
CMD ["sh", "-c", "alembic upgrade head || true; python -c 'import asyncio; from nexus.database.session import init_db; asyncio.run(init_db())'; uvicorn nexus.main:app --host 0.0.0.0 --port 8000"]
