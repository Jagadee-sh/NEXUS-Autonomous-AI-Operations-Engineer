# NEXUS — Data Model

All primary keys are UUID strings. All tables carry `created_at` (UTC). Soft business status fields where noted.

## Core identity
- **users**: id, email, hashed_password, full_name, role_id, is_active, created_at
- **roles**: id, name (admin|analyst|viewer), permissions (JSON)
- **organizations**: id, name, created_at; users.organization_id

## Knowledge & data
- **documents**: id, filename, content_type, size_bytes, status (uploaded|processing|ready|failed), error, source_type, organization_id, uploaded_by, created_at
- **document_chunks**: id, document_id FK, chunk_index, content, page, section, token_estimate, embedding JSON (memory store; pgvector in prod), metadata JSON, created_at
- **data_sources**: id, name, kind (sqlite|postgres), connection_url (encrypted-at-rest placeholder; env-referenced), status, created_at
- **datasets**: id, name, filename, status, row_count, columns JSON, stats JSON, created_at

## Agents & execution
- **agents**: id, name, role, description, tools JSON, is_active, created_at
- **tasks**: id, title, request, status (queued|running|succeeded|failed|cancelled|needs_approval), priority, user_id, trace_id, plan JSON, result JSON, confidence, error, max_retries, retry_count, created_at, started_at, finished_at
- **task_steps**: id, task_id FK, sequence, agent, step_type (plan|retrieve|analyze|sql|tool|validate|correct|report), status, input JSON, output JSON, error, latency_ms, created_at
- **agent_executions**: id, task_id FK, agent, iteration, status, started_at, finished_at, tokens_in, tokens_out, estimated_cost
- **messages**: id, task_id FK, role (user|assistant|system), content, metadata, created_at

## Evidence & quality
- **retrieval_results**: id, task_id, query, strategy, score, chunk_id, document_id, content_snippet, metadata, created_at
- **evidence**: id, task_id, claim, source_ref (chunk/doc/table), excerpt, strength, created_at
- **validation_results**: id, task_id, passed, score, issues JSON, unsupported_claims JSON, created_at
- **correction_attempts**: id, task_id, failure_category, strategy, description, succeeded, created_at

## Tools & governance
- **tools**: id, name, description, input_schema JSON, permission_level (LOW|MEDIUM|HIGH|CRITICAL), timeout_seconds, is_active
- **tool_executions**: id, task_id, tool_name, agent, arguments JSON, output_summary, status, latency_ms, risk_level, created_at
- **approval_requests**: id, task_id, action, risk_level, payload JSON, status (pending|approved|rejected), requested_by, decided_by, decided_at, reason, created_at
- **audit_logs**: id, actor, action, resource_type, resource_id, details JSON, ip, created_at

## Evaluation
- **evaluation_datasets**: id, name, description, items JSON, created_at
- **evaluation_runs**: id, dataset_id, status, metrics JSON, results JSON, started_at, finished_at, created_at
- **metrics**: id, run_id, name, value, slice, created_at

Indexes: tasks(trace_id), tasks(status), task_steps(task_id, sequence), document_chunks(document_id), retrieval_results(task_id), audit_logs(created_at), approval_requests(status).
