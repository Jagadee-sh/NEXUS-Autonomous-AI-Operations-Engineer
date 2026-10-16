# NEXUS — Product Requirements (MVP)

## Problem
Enterprises need a supervised AI control plane that can answer complex, multi-source questions with evidence, not vibes — and do so with auditability, safety gates, and measurable quality.

## Users
- **Analyst / Knowledge worker** — asks complex questions over documents + data.
- **Admin / Operator** — configures sources, reviews approvals, monitors health.
- **Evaluator** — runs datasets against the agent stack and compares versions.

## MVP capabilities (must actually work)
1. Ingest PDF / DOCX / TXT / CSV / XLSX; chunk, embed, index; ingestion status.
2. Hybrid retrieval (vector + BM25 + metadata filters) returning real citations.
3. Multi-agent task execution: Planner → workers → Validator → Report, with bounded retries.
4. Data analysis over uploaded CSV/XLSX: profiling, anomaly flags, NL questions → sandboxed pandas.
5. Read-only SQL over registered data sources (schema discovery, AST-enforced SELECT-only).
6. Governed tool system (permission levels, validation, audit).
7. Self-correction: detect failure (poor retrieval / invalid SQL / sandbox error / unsupported claim / timeout), classify, apply strategy, retry — visible in the trace.
8. Human approval gates for MEDIUM+ risk actions.
9. Evaluation runner over JSONL datasets with stored metrics.
10. Full traces + audit logs + health checks.
11. Web dashboard covering all of the above.
12. Works with zero paid APIs via deterministic `local` provider; real providers pluggable via env.

## Non-goals (MVP)
- Multi-tenant billing, SSO federation, mobile apps, arbitrary shell tools, DB write workflows, auto-scaling infra.

## Success criteria
A fresh developer follows the README, starts the stack, uploads demo data, runs the flagship Q3-profitability scenario, watches planner/agents/validation/correction in the trace, and receives an evidence-backed report with citations and confidence — with all automated tests green.
