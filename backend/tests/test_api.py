"""API integration tests via httpx ASGI client."""

from __future__ import annotations

from tests.conftest import DEMO_SALES_CSV, POLICY_TXT


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_ready(client):
    r = await client.get("/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["checks"]["database"] == "ok"


async def test_openapi_available(client):
    r = await client.get("/openapi.json")
    assert r.status_code == 200
    assert "NEXUS" in r.json()["info"]["title"]


async def test_upload_document_and_list(client):
    r = await client.post(
        "/api/v1/documents",
        files={"file": ("policy.txt", POLICY_TXT, "text/plain")},
    )
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["status"] == "ready"

    r2 = await client.get("/api/v1/documents")
    assert r2.status_code == 200
    assert any(d["id"] == doc["id"] for d in r2.json())


async def test_upload_dataset_and_get(client):
    r = await client.post(
        "/api/v1/datasets",
        files={"file": ("sales.csv", DEMO_SALES_CSV, "text/csv")},
    )
    assert r.status_code == 200, r.text
    ds = r.json()
    assert ds["status"] == "ready"
    assert ds["row_count"] == 8

    r2 = await client.get(f"/api/v1/datasets/{ds['id']}")
    assert r2.status_code == 200


async def test_reject_bad_upload(client):
    r = await client.post(
        "/api/v1/documents",
        files={"file": ("evil.exe", b"MZ9000", "application/octet-stream")},
    )
    assert r.status_code == 422


async def test_task_lifecycle_and_trace(client):
    # upload knowledge
    await client.post("/api/v1/documents", files={"file": ("policy.txt", POLICY_TXT, "text/plain")})
    ds = (
        await client.post("/api/v1/datasets", files={"file": ("sales.csv", DEMO_SALES_CSV, "text/csv")})
    ).json()

    r = await client.post(
        "/api/v1/query",
        json={
            "question": "Compare Q2 and Q3 revenue and state the travel approval threshold from policy.",
            "dataset_ids": [ds["id"]],
            "wait": True,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "succeeded"
    assert body["answer"]
    task_id = body["task_id"]

    trace = await client.get(f"/api/v1/tasks/{task_id}/trace")
    assert trace.status_code == 200
    t = trace.json()
    assert t["trace_id"]
    assert t["timeline"]
    step_types = {s["step_type"] for s in t["timeline"]}
    assert "plan" in step_types


async def test_agents_and_tools_endpoints(client):
    r = await client.get("/api/v1/agents")
    assert r.status_code == 200
    names = {a["name"] for a in r.json()}
    assert {"planner", "data_analyst", "validator", "report"} <= names

    r2 = await client.get("/api/v1/tools")
    assert r2.status_code == 200
    assert any(t["name"] == "document_search" for t in r2.json())


async def test_stats_endpoint(client):
    r = await client.get("/api/v1/stats")
    assert r.status_code == 200
    body = r.json()
    assert "tasks_total" in body and "documents" in body


async def test_approval_flow_via_api(client):
    # create pending approval through critical tool execution path in DB, then API approve
    from nexus.database.models import ApprovalRequest
    from nexus.database.session import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        req = ApprovalRequest(action="tool:admin_reset_metrics", risk_level="CRITICAL", payload={"tool": "admin_reset_metrics", "args": {}})
        session.add(req)
        await session.commit()
        await session.refresh(req)
        rid = req.id

    r = await client.get("/api/v1/approvals")
    assert r.status_code == 200
    assert any(a["id"] == rid for a in r.json())

    r2 = await client.post(f"/api/v1/approvals/{rid}/approve", json={"reason": "ok for demo"})
    assert r2.status_code == 200
    assert r2.json()["status"] == "approved"

    r3 = await client.post(f"/api/v1/approvals/{rid}/reject", json={"reason": "already decided"})
    assert r3.json()["status"] == "approved"  # idempotent, keeps first decision


async def test_evaluation_dataset_and_run(client):
    r = await client.post(
        "/api/v1/evaluations/datasets",
        json={
            "name": "Unit QA",
            "items": [
                {
                    "id": "t1",
                    "question": "What is 2+2? Summarize using any available data.",
                    "expected_answer": "four",
                    "expected_sources": [],
                }
            ],
        },
    )
    assert r.status_code == 200
    ds_id = r.json()["id"]

    r2 = await client.post("/api/v1/evaluations/run", json={"dataset_id": ds_id})
    assert r2.status_code == 200
    run = r2.json()
    assert run["status"] == "succeeded"
    assert "faithfulness" in run["metrics"]
    # metrics must be real: no errored items, task success > 0
    assert all(r.get("status") != "error" for r in run["results"]), run["results"]
    assert run["metrics"]["task_success_rate"] > 0
    assert run["metrics"]["faithfulness"] > 0

    r3 = await client.get(f"/api/v1/evaluations/runs/{run['id']}/metrics")
    assert r3.status_code == 200
    assert any(m["name"] == "faithfulness" for m in r3.json())
