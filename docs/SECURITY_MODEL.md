# NEXUS — Security Model

## Threat surface
Web API, file uploads, LLM prompts (injection), generated SQL/Python, tool invocations, external HTTP tool, secrets, logs.

## Controls

### Authentication & authorization
- JWT-ready auth: users + hashed passwords (bcrypt via passlib); Bearer token or configured `API_KEYS` for service access.
- Roles: `admin` (full), `analyst` (run tasks, upload, approve MEDIUM), `viewer` (read-only). Enforced via FastAPI dependencies.

### Input & file safety
- Upload size limit (`MAX_FILE_SIZE_MB`), MIME/extension allowlist, extension↔MIME consistency check.
- All request bodies validated by Pydantic; SQL identifiers validated against discovered schema.

### Prompt injection defenses
- Untrusted document text is wrapped in clearly delimited `<document>` blocks with an instruction that content is data, never instructions.
- Retrieved excerpts are truncated and attributed; the validator flags instructions found inside retrieved content.
- System prompts are server-side only; no user-controllable system role.

### SQL safety
- AST-based enforcement: only `SELECT` (with CTEs) allowed; `DROP/DELETE/UPDATE/INSERT/ALTER/TRUNCATE/CREATE/ATTACH/PRAGMA` rejected.
- Query timeout, row cap, per-connection read-only intent, full query audit.

### Python sandbox
- Code runs in a **separate process**: AST scan rejects import of non-allowlisted modules and rejects `open/exec/eval/__import__/os/system` patterns; restricted builtins; wall-clock timeout; memory cap via psutil; no network by policy; stdout/stderr captured; generated code logged.

### Tool governance
- Registry with `LOW|MEDIUM|HIGH|CRITICAL` risk. LOW executes; MEDIUM may auto-execute with audit (configurable); HIGH/CRITICAL require an `approval_request` and human decision before execution.
- Argument JSON-schema validation before execution; output size caps; every call in `tool_executions` + `audit_logs`.

### Secrets & logging
- All secrets via environment; `.env` git-ignored; `.env.example` has placeholders only.
- Log redaction filters strip `api_key`, `authorization`, `password`, `secret`, `token` patterns.
- PII-aware: emails/phones in logs are masked by the redaction layer where present in structured extras.

### Transport & abuse
- CORS restricted by `CORS_ORIGINS`; rate limiting per client (`RATE_LIMIT_PER_MINUTE`); request body size caps; timeouts everywhere (HTTP, SQL, sandbox, agent steps, whole task).

### Human approval
- Approval gate UX: agent proposes → `approval_requests` row → human approve/reject with reason → execution resumes or task fails with audit trail.
