# NEXUS Enterprise Architecture Audit

## Scope and finding

This audit is based on the repository as it exists before the NEXUS Omega extension. NEXUS is a FastAPI, SQLAlchemy, React/Vite control plane with a custom typed workflow engine rather than LangGraph. The existing system is substantial and should be extended, not replaced.

## Current architecture

```text
React dashboard
    -> FastAPI /api/v1
    -> authentication, rate limiting, CORS, audit helpers
    -> in-process or Redis-backed task queue
    -> WorkflowEngine
       planner -> routed workers -> validator -> report
                    ^                 |
                    |-- self-correction/retry --|
    -> SQLAlchemy persistence (SQLite default, PostgreSQL supported)
```

The runtime is split into `backend/nexus` and `frontend/src`. The backend defaults to deterministic local LLM and embedding providers, SQLite, and memory retrieval so tests and demos can run without paid services.

## Major components

- `backend/nexus/api/`: FastAPI routers for tasks, knowledge, data sources, admin, auth, approvals, evaluations, and demos.
- `backend/nexus/orchestration/`: `WorkflowState` plus the custom stateful `WorkflowEngine` in `engine.py`.
- `backend/nexus/agents/core.py`: planner, retrieval/research, data analysis, SQL, tool, validator, and report agents.
- `backend/nexus/retrieval/` and `backend/nexus/ingestion/`: document extraction, chunking, deterministic embeddings, BM25/vector retrieval, fusion, reranking, and citations.
- `backend/nexus/execution/`: read-only SQL validation/execution and a process-based restricted Python sandbox.
- `backend/nexus/tools/`: tool registry, argument validation, permission levels, approvals, execution records, and audit records.
- `backend/nexus/evaluation/`: dataset-driven workflow evaluation and deterministic lexical metrics.
- `backend/nexus/database/`: SQLAlchemy models and async sessions; `alembic/versions/0001_initial.py` is the only migration.
- `backend/nexus/observability/`: database-backed trace assembly and redacted structured logging.
- `frontend/src/`: React Router shell, operational pages, local React state, polling API client, and Tailwind utility classes.

## Data flow

1. A task is created by `api/v1/tasks.py` and persisted with a `trace_id`.
2. The queue invokes `run_workflow()` in `orchestration/engine.py`.
3. `prepare_state()` resolves documents, datasets, and data source schema into `WorkflowState`.
4. The planner creates typed `PlanStep` objects. The engine dispatches steps to existing agents.
5. Retrieval, SQL, data analysis, and tools write results into state and persistence models.
6. The validator checks evidence and claims. Failed validation creates a correction attempt and retries within configured bounds.
7. The report agent creates the final answer. Task, step, validation, evidence, and correction rows are persisted.
8. The UI polls task and trace endpoints to show progress and outcomes.

## Agent and workflow flow

NEXUS uses a custom graph equivalent, not LangGraph. The documented flow is:

```text
START -> planner -> router -> research/retrieval/data_analyst/sql_analyst/tool
      -> validator -- pass -> report -> END
                  \-- fail -> self-correction -> bounded retry
```

The actual engine is intentionally deterministic and testable. `WorkflowState` contains task identity, request, plan, retrieval, tool, SQL, analysis, evidence, validation, corrections, errors, final answer, confidence, and metadata. This state is the primary integration point for Omega execution traces.

## RAG flow

`ingestion/pipeline.py` extracts PDF, DOCX, text, Markdown, CSV, and XLSX content, chunks it with page/section metadata, embeds it, and stores document chunks. `retrieval/hybrid.py` combines vector similarity and BM25 with reciprocal-rank fusion and lexical reranking. Retrieval results carry chunk/document identifiers, scores, citations, and prompt-injection markers. The current local embedding and process-local BM25 paths are deterministic but are not production-grade semantic/index infrastructure.

## Database structure

Existing models cover organizations, users, roles, documents/chunks, datasets/data sources, agents, tasks, task steps, agent executions, messages, retrieval results, evidence, validations, correction attempts, tools/tool executions, approvals, audit logs, evaluation datasets/runs, and metrics. JSON columns are used for plans, inputs, outputs, results, and metric bundles.

Startup calls `Base.metadata.create_all()` and Alembic has a broad initial migration. Omega must add explicit additive migrations and must not replace or transform existing storage.

## Frontend structure

`frontend/src/App.tsx` defines routes under the shared `Layout`. Existing pages cover dashboard, workspace, agents, knowledge, data sources, traces, evaluations, approvals, health, and settings. `frontend/src/lib/api.ts` is the typed API boundary. Existing styles use dark slate/cyan cards, status badges, responsive grids, and polling. Omega should add a sibling `/evolution` route and reuse these primitives.

## Observability

`TraceRecorder` persists ordered task steps with inputs, outputs, status, errors, and latency. Task trace assembly also exposes validations, corrections, evidence, and tool calls. `AgentExecution`, `RetrievalResult`, `AuditLog`, and structured redacted logging provide additional records. Model/prompt/config versions, explicit execution events, token/cost data, and correlation propagation are incomplete and are the first safe tracing extensions.

## Existing self-healing loop

`self_correction/classifier.py` classifies retrieval, evidence, SQL, Python, tool, grounding, context, conflict, and timeout failures. `orchestration/engine.py` records `CorrectionAttempt`, adds correction history to the task result, broadens or changes retrieval strategy for selected diagnoses, and retries until `max_retries`. This is operational recovery inside one task. It is not yet an evolution loop and must remain separate from Omega's cross-execution analysis.

## Existing evaluation capability

`evaluation/runner.py` runs real tasks from persisted evaluation datasets and records item results and aggregate metrics: keyword answer recall, groundedness, retrieval relevance, task success, correction success, and latency. `research/strategies.py` already supports retrieval-strategy comparison. Metrics are deterministic lexical heuristics and evaluation is synchronous in the API path. Omega should reuse these metric functions and add versioned, reproducible experiment metadata rather than inventing fake scores.

## Reusable extension points

1. Extend the existing SQLAlchemy model registry and Alembic migration additively for Omega records.
2. Extend `TraceRecorder` and/or add an execution event service at the workflow boundary.
3. Reuse `run_evaluation()` and retrieval research for benchmark adapters.
4. Add an `evolution` service/controller beside `evaluation` and `research`, not a second workflow framework.
5. Register an evolution router in `main.py` under the existing API prefix and auth dependencies.
6. Add typed API models and an `Evolution` page under the existing frontend layout.
7. Reuse `execution/sandbox.py` for candidate evaluation; prohibit arbitrary generated host code and production writes.
8. Reuse approvals and audit logs for controlled promotion decisions.

## Risks and constraints

- Ownership/tenant checks are incomplete across existing read APIs; Omega must not widen access.
- Workflow timeout configuration is measured but not enforced with cancellation.
- Task claiming can duplicate work across workers.
- The sandbox is process-level and its configured memory limit is not fully enforced in the execution path.
- `pgvector` and BM25 production paths are not fully durable/scalable.
- Existing evaluation lacks model/prompt/workflow/version metadata.
- Evaluation can block an API request and should be queued for larger experiments.
- Anonymous analyst access is possible in development when API keys are empty; promotion must require explicit authorization.
- Stored prompts, outputs, and tool payloads may contain sensitive data; Omega traces require redaction and bounded payloads.
- Failure injection is useful for demos/tests but must remain restricted outside development.

## Proposed NEXUS Omega architecture

Omega sits above, and does not replace, the operational workflow:

```text
NEXUS task execution
  -> immutable/redacted execution events
  -> Evaluation + failure analysis
  -> evidence-backed capability gaps
  -> hypotheses -> immutable candidates/versions
  -> isolated benchmark experiment
  -> multi-objective governance decision
  -> approval-gated promotion or rejection
  -> post-promotion verification and deterministic rollback
  -> evolution memory
```

The first implementation should establish durable schemas and trace metadata. Later phases can add analysis, candidate execution, governance, and UI incrementally. Stable NEXUS versions remain active unless a recorded, policy-compliant promotion changes an explicitly selected component.
