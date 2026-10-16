"""Run all four NEXUS flagship demos against a running API server.

Usage:
    python scripts/run_flagship_demos.py [--base http://localhost:8000] [--demo all|q3|correction|research|churn]

Demos:
  1. q3         — Q3 profitability decline analysis with document citations
  2. correction — self-correction loop with a simulated failure (visible in trace)
  3. research   — retrieval strategy comparison experiment (vector vs keyword vs hybrid)
  4. churn      — customer churn analysis across segments and reasons
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

CHURN_QUESTION = (
    "Analyze customer churn: what is the churn rate, which segments churn most, and why?"
)


def _ok(label: str, detail: str = "") -> None:
    print(f"PASS | {label}" + (f" {detail}" if detail else ""))


def _fail(label: str, detail: str = "") -> None:
    print(f"FAIL | {label}" + (f" {detail}" if detail else ""))
    raise SystemExit(1)


def _ensure_demo(c: httpx.Client) -> None:
    docs = c.get("/api/v1/documents")
    if docs.status_code == 200 and len(docs.json()) >= 3:
        _ok("demo data present", f"{len(docs.json())} documents")
        return
    r = c.post("/api/v1/demo/load")
    if r.status_code != 200:
        _fail("demo load", r.text[:300])
    body = r.json()
    _ok("demo loaded", json.dumps({k: body[k] for k in ("documents", "datasets") if k in body}))


def _pick_dataset(c: httpx.Client, name_contains: str) -> str | None:
    r = c.get("/api/v1/datasets")
    if r.status_code != 200:
        return None
    for d in r.json():
        if name_contains.lower() in (d.get("filename") or "").lower() and d.get("status") == "ready":
            return d["id"]
    return None


def demo_q3(c: httpx.Client) -> str | None:
    sales_id = _pick_dataset(c, "sales")
    r = c.post(
        "/api/v1/query",
        json={
            "question": (
                "Analyze why profitability declined in Q3. Compare Q2 and Q3, identify "
                "the top three contributing factors, verify findings using company "
                "documents, and provide three recommended actions."
            ),
            "dataset_ids": [sales_id] if sales_id else [],
            "wait": True,
        },
    )
    if r.status_code != 200:
        _fail("q3 query", r.text[:300])
    body = r.json()
    if body.get("status") != "succeeded" or not body.get("answer"):
        _fail("q3 succeeded", str(body.get("status")) + " " + str(body.get("error"))[:200])
    citations = (body.get("citations") or [])
    if not citations:
        _fail("q3 citations")
    answer = body["answer"]
    if "Q3" not in answer and "q3" not in answer:
        _fail("q3 answer content")
    _ok("q3 analysis", f"answer {len(answer)} chars, {len(citations)} citations, task={body['task_id']}")
    return body["task_id"]


def demo_correction(c: httpx.Client) -> str | None:
    r = c.post(
        "/api/v1/query",
        json={
            "question": "What travel amount requires VP approval according to policy documents?",
            "wait": True,
            "failure_injection": {"category": "poor_retrieval", "fail_first": 1},
        },
    )
    if r.status_code != 200:
        _fail("correction query", r.text[:300])
    body = r.json()
    if body.get("status") != "succeeded":
        _fail("correction succeeded", str(body.get("status")))
    task_id = body["task_id"]
    t = c.get(f"/api/v1/tasks/{task_id}/trace").json()
    corrections = t.get("corrections") or []
    validations = t.get("validations") or []
    if not corrections:
        _fail("correction recorded")
    if not validations or validations[0].get("passed") is not False:
        _fail("injected failure visible in trace")
    print(
        f"PASS | self-correction: {validations[0].get('issues', [''])[0][:80]} "
        f"-> {corrections[0].get('strategy')} (succeeded={corrections[0].get('succeeded')}); "
        f"{len(validations)} validations total"
    )
    return task_id


def demo_research(c: httpx.Client) -> str | None:
    ds_list = c.get("/api/v1/evaluations/datasets")
    dataset_id = None
    if ds_list.status_code == 200:
        with_items = [d for d in ds_list.json() if d.get("items")]
        dataset_id = with_items[0]["id"] if with_items else None
    r = c.post(
        "/api/v1/evaluations/research/retrieval-comparison",
        json={"dataset_id": dataset_id},
    )
    if r.status_code != 200:
        _fail("research run", r.text[:300])
    run = r.json()
    if run.get("status") != "succeeded":
        _fail("research succeeded", str(run.get("status")))
    m = run["metrics"]
    print(
        "PASS | retrieval research: "
        + " · ".join(
            f"{s}={m.get(f'{s}_combined')}" for s in ("vector", "keyword", "hybrid")
        )
        + f" · best={m.get('best_strategy')}"
    )
    return run["id"]


def demo_churn(c: httpx.Client) -> str | None:
    customers_id = _pick_dataset(c, "customers")
    r = c.post(
        "/api/v1/query",
        json={
            "question": CHURN_QUESTION,
            "dataset_ids": [customers_id] if customers_id else [],
            "wait": True,
        },
    )
    if r.status_code != 200:
        _fail("churn query", r.text[:300])
    body = r.json()
    if body.get("status") != "succeeded":
        _fail("churn succeeded", str(body.get("status")))
    findings = ((body.get("result") or {}).get("findings")) or []
    churn_findings = [f for f in findings if "churn" in str(f.get("metric", "")).lower()]
    if not churn_findings:
        _fail("churn findings", f"got {[f.get('metric') for f in findings]}")
    _ok(
        "churn analysis",
        f"{len(churn_findings)} churn findings, first={churn_findings[0].get('metric')}={churn_findings[0].get('detail')}",
    )
    return body["task_id"]


DEMOS = {
    "q3": demo_q3,
    "correction": demo_correction,
    "research": demo_research,
    "churn": demo_churn,
}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows cp1252 consoles
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="Run NEXUS flagship demos")
    ap.add_argument("--base", default="http://localhost:8000", help="API base URL (no /api/v1)")
    ap.add_argument("--demo", default="all", choices=["all", *DEMOS])
    ap.add_argument(
        "--pause",
        type=float,
        default=18.0,
        help="Seconds to wait between demos (Groq free tier is ~8k TPM; let the window reset)",
    )
    args = ap.parse_args()

    import time

    with httpx.Client(base_url=args.base, timeout=300.0) as c:
        h = c.get("/health")
        if h.status_code != 200:
            print(f"server not reachable at {args.base} — start it with: uvicorn nexus.main:app --port 8000")
            return 2
        _ok("server health", h.text[:120])
        _ensure_demo(c)

        order = list(DEMOS) if args.demo == "all" else [args.demo]
        for i, name in enumerate(order):
            if i:
                print(f"(pausing {args.pause:.0f}s for rate-limit headroom)")
                time.sleep(args.pause)
            print(f"--- demo: {name} ---")
            try:
                DEMOS[name](c)
            except SystemExit:
                raise
            except Exception as exc:  # noqa: BLE001
                print(f"error: {exc}")
                raise SystemExit(1) from None

    print("\nAll selected flagship demos PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
