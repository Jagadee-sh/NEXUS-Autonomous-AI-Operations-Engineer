# NEXUS — Agent Evaluation Plan

## Dataset format (JSONL or JSON array)
```json
{
  "id": "q3-profitability",
  "question": "Why did profitability decline in Q3? Compare Q2 and Q3.",
  "expected_answer": "…key facts…",
  "expected_sources": ["annual_report.pdf", "sales.csv"],
  "expected_keywords": ["Q3", "margin", "expense"],
  "metadata": {"suite": "flagship"}
}
```

## Metrics
| Metric | How computed |
|---|---|
| answer_correctness | keyword/phrase recall vs `expected_answer` + optional LLM judge |
| faithfulness / groundedness | fraction of answer claims supported by retrieved evidence (token-overlap) |
| retrieval_relevance | rank-weighted overlap of retrieved chunks with expected sources/keywords |
| context_precision | share of retrieved chunks containing expected keywords |
| tool_success_rate | successful tool executions / total |
| sql_success_rate | successful SQL executions / total SQL attempts |
| correction_success_rate | corrections that led to validator pass / total corrections |
| latency, tokens, estimated_cost | from agent_executions / task timings |

## Runner
`POST /api/v1/evaluations/run` → for each item, run the full agent workflow (using configured provider; tests use `local`) → score → persist `evaluation_runs` + `metrics` → comparable across runs (same dataset, different provider/version).

## Gates
CI runs the deterministic suite (local provider). Frontend groundedness dashboard reads latest run metrics.
