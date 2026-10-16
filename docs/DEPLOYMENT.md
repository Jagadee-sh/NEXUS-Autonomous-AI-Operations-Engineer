# NEXUS — Deployment

## Guaranteed path: local Docker Compose
```bash
cp .env.example .env   # edit secrets
docker compose up --build
```
Services: `postgres` (pgvector image), `redis`, `backend` (API), `worker` (queue consumer), `frontend` (nginx serving build + proxying /api).
Healthchecks: `/health` on backend; postgres/redis native checks; worker heartbeats via task lease.

## Local dev without Docker
```bash
# backend (SQLite + in-process queue by default)
cd backend && python -m venv .venv && .venv\Scripts\activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn nexus.main:app --reload --port 8000
# worker (optional separate process; in-process worker also runs in API for dev)
python -m nexus.workers.app
# frontend
cd frontend && npm install && npm run dev
```

## Cloud sketches
- **AWS**: ECS Fargate (backend/worker) + RDS Postgres (pgvector via extension on Aurora PG or self-managed) + ElastiCache Redis + S3 for uploads + ALB. Secrets in Secrets Manager.
- **Azure**: Container Apps + Azure PostgreSQL Flexible + Azure Cache for Redis + Key Vault.
- **GCP**: Cloud Run + Cloud SQL (Postgres) + Memorystore + Secret Manager.
- **VPS**: single host, docker compose, Caddy/nginx TLS, scheduled backups of the Postgres volume.

Production checklist: strong `NEXUS_SECRET_KEY`, Postgres+pgvector, Redis enabled, HTTPS termination, restricted `CORS_ORIGINS`, `API_KEYS` or SSO front door, log shipping, nightly DB backups.
