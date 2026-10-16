# NEXUS — Implementation Plan

| Phase | Deliverable | Status |
|---|---|---|
| 0 | Repo audit, architecture, requirements, security model | done |
| 1 | Backend foundation: config, DB models, migrations, logging, health, auth-ready | done |
| 2 | Ingestion, chunking, embeddings, vector + BM25 hybrid retrieval, citations | done |
| 3 | Orchestration engine + 8 agents (planner, research, retrieval, data analyst, SQL analyst, tool, validator, report) | done |
| 4 | Read-only SQL engine, Python sandbox, tool system with permissions | done |
| 5 | Self-correction engine (classify → strategy → retry → validate) | done |
| 6 | Evaluation framework (datasets, metrics, runner, comparison) + research engine (retrieval strategy experiments) | done |
| 7 | Observability (trace IDs, step timelines, redaction, audit logs) | done |
| 8 | Frontend dashboard (10 pages, trace viewer, live-polling workspace with self-correction demo toggle) | done |
| 9 | Approvals, RBAC, rate limiting, file validation, prompt-injection defenses, seeded auth users (login + roles) | done |
| 10 | Demo datasets/documents + seed script + four flagship scenarios + `scripts/run_flagship_demos.py` runner | done |
| 11 | Unit/integration/API/security tests (71 backend + 5 frontend), fixes | done |
| 12 | Docker, Compose, GitHub Actions, deployment docs, README | done |

Each phase: implement → test → fix → document → next phase.
