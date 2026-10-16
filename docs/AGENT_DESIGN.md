# NEXUS — Agent Design

## Principles
- Each agent has a **single explicit responsibility**, a **typed input/output contract**, and its own prompt/logic module.
- Agents never call each other directly; the **WorkflowEngine** routes state between them.
- Every agent run is bounded by **iteration limits** and **timeouts**.
- Agents that need an LLM go through `LLMProvider`; the deterministic `local` provider implements heuristics so the system remains useful without keys.

## WorkflowState (orchestration)
`task`, `user_id`, `plan`, `current_step`, `messages`, `retrieved_documents`, `tool_calls`, `tool_results`, `sql_results`, `analysis_results`, `evidence`, `validation_results`, `errors`, `retry_count`, `correction_history`, `final_answer`, `confidence`, `trace_id`.

## Graph
```
START → planner → router
  router → research | retrieval | data_analyst | sql_analyst | tool_agent  (may run several)
  → validator
  validator.pass → report → END
  validator.fail → self_correct → planner (retry_count++ until max_retries) → …
```

## Agents

| Agent | Input | Output | LLM use |
|---|---|---|---|
| **Planner** | task text + available sources | ordered `PlanStep[]` with agent, goal, inputs | optional; heuristic fallback decomposes by keywords |
| **Retrieval** | query + filters | ranked chunks w/ scores + citations | embedding-based; rerank optional |
| **Research** | plan step + knowledge need | synthesized evidence bundle + citations | synthesizes retrieved text; extraction works locally |
| **DataAnalyst** | dataset + question | profile → pandas code → sandbox exec → findings | generates code via LLM or heuristics (describe/anomaly/zscore) |
| **SQLAnalyst** | schema + question | validated SELECT → exec → summary | LLM or heuristic SQL; AST validation always |
| **Tool** | tool name + args | permission check → validated call → audited output | arg validation always |
| **Validator** | answer + evidence + retrievals | pass/fail, score, issues, unsupported claims | rule-based groundedness (claim↔evidence overlap) + optional LLM critique |
| **Report** | all state | executive summary, findings, citations, confidence, limitations, recommendations | template assembly + optional LLM polish |

## Self-correction categories
`poor_retrieval`, `missing_evidence`, `invalid_sql`, `sql_execution_failure`, `python_execution_failure`, `tool_failure`, `unsupported_claim`, `insufficient_context`, `conflicting_evidence`, `timeout`.

Strategies: query rewrite, retrieval strategy change, reranking, SQL regeneration, analysis regeneration, tool retry, plan modification, clarification request. Every attempt is stored in `correction_attempts` and shown in the UI trace.
