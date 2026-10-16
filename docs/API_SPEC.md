# NEXUS — API Spec (v1)

Base: `/api/v1` · Auth: `Authorization: Bearer <jwt-or-api-key>` (when `API_KEYS` set) · All bodies JSON unless noted.

## Health
- `GET /health` → `{status, version, time}` (no auth)
- `GET /ready` → readiness of db/redis/vector/llm

## Auth
- `POST /auth/login` `{email, password}` → `{access_token, token_type, user}`
- `GET /auth/me` → current user

## Tasks
- `POST /tasks` `{title?, request, priority?, dataset_ids?, document_ids?, datasource_id?}` → task (queued)
- `GET /tasks?status=&limit=&offset=` → list
- `GET /tasks/{id}` → task detail (+result, confidence)
- `GET /tasks/{id}/trace` → ordered steps, retrievals, tool calls, validations, corrections
- `POST /tasks/{id}/cancel`

## Query (sync convenience)
- `POST /query` `{question, document_ids?, dataset_ids?, datasource_id?, wait?=true}` → runs workflow inline (wait) or returns task

## Documents
- `POST /documents` multipart `file` → document (processing→ready)
- `GET /documents` · `GET /documents/{id}` · `DELETE /documents/{id}`

## Datasets
- `POST /datasets` multipart `file` (csv/xlsx) → dataset with profile
- `GET /datasets` · `GET /datasets/{id}`

## Data sources
- `POST /datasources` `{name, kind, connection_url}` · `GET /datasources` · `POST /datasources/{id}/test` · `GET /datasources/{id}/schema`

## Agents & tools
- `GET /agents` → registry + recent performance
- `GET /tools` → tool catalog with schemas/permissions

## Approvals
- `GET /approvals?status=pending`
- `POST /approvals/{id}/approve` `{reason?}` · `POST /approvals/{id}/reject` `{reason}`

## Evaluations
- `GET /evaluations/datasets` · `POST /evaluations/datasets` `{name, items[]}`
- `POST /evaluations/run` `{dataset_id}` → run
- `GET /evaluations/runs` · `GET /evaluations/runs/{id}`

## Audit
- `GET /audit?limit=` (admin)
