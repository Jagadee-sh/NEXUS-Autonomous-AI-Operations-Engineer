"""Deterministic local provider.

Implements useful heuristics so NEXUS remains fully functional without paid APIs.
Real providers (OpenAI/Anthropic/Gemini/Ollama) are used when configured.
"""

from __future__ import annotations

import json
import re

from nexus.llm.base import LLMMessage, LLMProvider, LLMResponse

_NUM = re.compile(r"q([1-4])", re.I)


def _extract_quarters(text: str) -> list[int]:
    found = {int(m.group(1)) for m in _NUM.finditer(text)}
    return sorted(found) or [2, 3]


class LocalLLMProvider(LLMProvider):
    """Rule-based completions keyed off the last user message."""

    name = "local"

    def healthy(self) -> bool:
        return True

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        timeout: float = 60.0,
    ) -> LLMResponse:
        system = " ".join(m.content for m in messages if m.role == "system")
        user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        content = self._route(system, user)
        return LLMResponse(
            content=content,
            tokens_in=len(system.split()) + len(user.split()),
            tokens_out=len(content.split()),
            estimated_cost=0.0,
            model="local-heuristic",
        )

    # ------------------------------------------------------------------
    def _route(self, system: str, user: str) -> str:
        s = (system + "\n" + user).lower()
        if "plan the task" in s or "you are the planner" in s:
            return self._plan(user)
        if "generate a sql" in s or "you are the sql analyst" in s:
            return self._sql(user)
        if "write pandas" in s or "you are the data analyst" in s or "generate python" in s:
            return self._python(user)
        if "synthesize evidence" in s or "you are the research" in s:
            return self._research(user)
        if "polish" in s or "executive report" in s or "you are the report" in s:
            return self._report(user)
        if "critique" in s or "validate" in s:
            return json.dumps({"verdict": "ok", "notes": "local heuristic validation"})
        return self._generic(user)

    def _plan(self, user: str) -> str:
        text = user.lower()
        steps: list[dict] = []
        wants_docs = any(k in text for k in ("document", "report", "policy", "evidence", "citation", "annual", "verify", "supporting"))
        wants_data = any(k in text for k in ("dataset", "csv", "sales", "revenue", "expense", "profit", "analyze", "anomaly", "churn", "compare", "q2", "q3"))
        wants_sql = any(k in text for k in ("sql", "database", "query the", "table"))
        wants_research = any(k in text for k in ("research", "compare strategies", "hypothesis", "experiment"))
        quarters = _extract_quarters(text)
        if not (wants_docs or wants_data or wants_sql or wants_research):
            wants_docs = True
        if wants_data:
            steps.append({
                "agent": "data_analyst",
                "goal": f"Profile and analyze tabular data; compare periods {quarters}; compute contributions and anomalies.",
                "inputs": ["datasets"],
            })
        if wants_sql:
            steps.append({"agent": "sql_analyst", "goal": "Inspect schema and run read-only SQL to answer quantitative questions.", "inputs": ["datasource"]})
        if wants_docs:
            steps.append({
                "agent": "research",
                "goal": "Retrieve and synthesize supporting evidence from knowledge documents with citations.",
                "inputs": ["documents"],
            })
        if wants_research:
            steps.append({"agent": "research", "goal": "Form hypotheses, run comparative experiments, and report results.", "inputs": ["documents", "datasets"]})
        steps.append({"agent": "validator", "goal": "Verify findings against evidence and data.", "inputs": ["evidence"]})
        steps.append({"agent": "report", "goal": "Produce executive report with citations, confidence, limitations, recommendations.", "inputs": ["all"]})
        return json.dumps({"summary": "Multi-step plan: analyze, gather evidence, validate, report.", "steps": steps})

    def _sql(self, user: str) -> str:
        text = user.lower()
        m = re.search(r"table[:\s]+([a-zA-Z_][a-zA-Z0-9_]*)", text)
        table = m.group(1) if m else None
        if not table:
            m2 = re.search(r"from\s+([a-zA-Z_][a-zA-Z0-9_]*)", text)
            table = m2.group(1) if m2 else None
        if "count" in text and table:
            return f'SELECT COUNT(*) AS row_count FROM "{table}";'
        if table:
            return f'SELECT * FROM "{table}" LIMIT 50;'
        return "SELECT 1 AS ok;"

    def _python(self, user: str) -> str:
        # Conservative: profile the dataframe `df` that the sandbox preloads.
        if any(k in user.lower() for k in ("anomaly", "outlier", "unusual", "zscore", "z-score")):
            return (
                "import pandas as pd, numpy as np\n"
                "num = df.select_dtypes(include='number')\n"
                "z = (num - num.mean()) / (num.std(ddof=0) + 1e-9)\n"
                "mask = (z.abs() > 3).any(axis=1)\n"
                "result = df[mask].head(20).to_dict(orient='records')\n"
                "summary = {'anomaly_rows': int(mask.sum()), 'columns_checked': list(num.columns)}\n"
            )
        return (
            "import pandas as pd, numpy as np\n"
            "summary = {'rows': int(len(df)), 'columns': list(df.columns), "
            "'dtypes': {c: str(t) for c, t in df.dtypes.items()}, "
            "'missing': {c: int(df[c].isna().sum()) for c in df.columns}}\n"
            "num = df.describe().to_dict()\n"
            "result = {'profile': summary, 'describe': num}\n"
        )

    def _research(self, user: str) -> str:
        # Synthesize bullet points from provided excerpts in the prompt.
        excerpts = re.findall(r"<excerpt[^>]*>(.*?)</excerpt>", user, flags=re.S)
        if not excerpts:
            # fallback: lines after EXCERPTS:
            m = re.search(r"EXCERPTS:\s*(.*)", user, flags=re.S)
            excerpts = [m.group(1)[:500]] if m else [user.strip()[:500]]
        bullets = "\n".join(f"- {e.strip()[:280]}" for e in excerpts[:6])
        return f"Key synthesized evidence:\n{bullets}"

    def _report(self, user: str) -> str:
        return (
            "EXECUTIVE SUMMARY\n"
            "Findings were produced by the NEXUS agent pipeline from uploaded datasets and documents.\n\n"
            "FINDINGS\n"
            "1. See structured findings from the Data Analyst step.\n"
            "2. Supporting document evidence is cited below.\n\n"
            "RECOMMENDATIONS\n"
            "1. Review the top contributing factors identified in the analysis.\n"
            "2. Tighten controls on the largest cost drivers.\n"
            "3. Re-run the analysis monthly to monitor the trend.\n"
        )

    def _generic(self, user: str) -> str:
        return f"Local heuristic response. Task received: {user[:200]}"
