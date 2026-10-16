"""Tests for bootstrap users, failure injection demo, research experiment, churn analysis."""

from __future__ import annotations

from sqlalchemy import select

from nexus.database.models import CorrectionAttempt, EvaluationDataset, User, ValidationResult
from nexus.ingestion.pipeline import ingest_document
from nexus.orchestration.engine import run_workflow
from nexus.services.dataset_service import ingest_dataset
from tests.conftest import POLICY_TXT

CHURN_CSV = b"""customer_id,segment,monthly_charges,tenure_months,churned,churn_reason
1,Enterprise,300,12,1,price
2,Enterprise,320,8,1,price
3,SMB,90,24,0,
4,SMB,95,30,0,
5,Enterprise,290,6,1,support
6,SMB,85,18,0,
7,SMB,88,3,1,price
8,Startup,50,10,0,
"""


async def test_bootstrap_users_created_once(session):
    from nexus.core.bootstrap import DEV_ADMIN_EMAIL, DEV_ANALYST_EMAIL, ensure_default_users

    created = await ensure_default_users(session)
    assert set(created) == {DEV_ADMIN_EMAIL, DEV_ANALYST_EMAIL}
    users = (await session.execute(select(User))).scalars().all()
    assert len(users) == 2
    # idempotent
    again = await ensure_default_users(session)
    assert again == []
    users = (await session.execute(select(User))).scalars().all()
    assert len(users) == 2


async def test_failure_injection_triggers_visible_self_correction(session):
    await ingest_document(session, filename="policy.txt", content=POLICY_TXT)
    task = _task_with_injection()
    session.add(task)
    await session.commit()
    await session.refresh(task)
    task = await run_workflow(session, task.id)

    assert task.status == "succeeded"
    validations = (
        await session.execute(select(ValidationResult).where(ValidationResult.task_id == task.id))
    ).scalars().all()
    assert len(validations) >= 2  # injected failure + recovery
    assert validations[0].passed is False
    assert any("demo injection" in (i or "") for i in validations[0].issues)
    corrections = (
        await session.execute(select(CorrectionAttempt).where(CorrectionAttempt.task_id == task.id))
    ).scalars().all()
    assert corrections, "injected failure must produce a recorded correction attempt"
    assert corrections[0].succeeded is True


def _task_with_injection():
    from nexus.database.models import Task

    return Task(
        request="What travel amount requires VP approval according to policy documents?",
        context={
            "user_role": "analyst",
            "failure_injection": {"category": "poor_retrieval", "fail_first": 1},
        },
        max_retries=3,
    )


async def test_retrieval_strategy_research_experiment(session):
    from nexus.research.strategies import STRATEGIES, run_retrieval_comparison

    await ingest_document(session, filename="policy.txt", content=POLICY_TXT)
    ds = EvaluationDataset(
        name="Research Items",
        items=[
            {
                "id": "r1",
                "question": "What travel amount requires VP approval?",
                "expected_sources": ["policy.txt"],
                "expected_answer": "Travel expenses above 2000 require VP approval",
            }
        ],
    )
    session.add(ds)
    await session.commit()
    await session.refresh(ds)

    run = await run_retrieval_comparison(session, dataset_id=ds.id, top_k=4)
    assert run.status == "succeeded"
    for strategy in STRATEGIES:
        assert f"{strategy}_combined" in run.metrics
        assert f"{strategy}_hit_rate" in run.metrics
        assert f"{strategy}_latency_ms" in run.metrics
    assert run.metrics["best_strategy"] in STRATEGIES
    # keyword retrieval must find the policy chunk for this question
    assert run.metrics["keyword_hit_rate"] > 0
    assert run.results and run.results[0]["strategies"]["keyword"]["hits"] > 0

    # metrics recorded with slices
    from nexus.database.models import Metric

    rows = (await session.execute(select(Metric).where(Metric.run_id == run.id))).scalars().all()
    slices = {m.slice for m in rows}
    assert slices == set(STRATEGIES)


async def test_adhoc_research_questions_persist(session):
    from nexus.research.strategies import RESEARCH_DATASET_NAME, run_retrieval_comparison

    await ingest_document(session, filename="policy.txt", content=POLICY_TXT)
    run = await run_retrieval_comparison(
        session, questions=["What does the policy say about churn review triggers?"], top_k=3
    )
    assert run.status == "succeeded"
    ds = (
        await session.execute(select(EvaluationDataset).where(EvaluationDataset.name == RESEARCH_DATASET_NAME))
    ).scalars().first()
    assert ds and ds.items
    assert ds.items[0]["question"].startswith("What does the policy")


async def test_churn_analysis_flagship(session):
    ds = await ingest_dataset(session, filename="customers.csv", content=CHURN_CSV, name="Customers")
    task = _churn_task(ds.id)
    session.add(task)
    await session.commit()
    await session.refresh(task)
    task = await run_workflow(session, task.id)
    assert task.status == "succeeded"
    findings = (task.result or {}).get("findings") or []
    churn_findings = [f for f in findings if "churn" in str(f.get("metric", "")).lower()]
    assert churn_findings, f"expected churn findings, got: {[f.get('metric') for f in findings]}"
    assert churn_findings[0]["metric"] == "churn_rate"
    # detail is the serialized metric value (e.g. 50.0)
    assert float(str(churn_findings[0]["detail"]).strip('"')) >= 0


def _churn_task(dataset_id: str):
    from nexus.database.models import Task

    return Task(
        request="Analyze customer churn: what is the churn rate, which segments churn most, and why?",
        context={"dataset_ids": [dataset_id], "user_role": "analyst"},
        max_retries=2,
    )


async def test_query_endpoint_supports_failure_injection(client):
    await client.post("/api/v1/documents", files={"file": ("policy.txt", POLICY_TXT, "text/plain")})
    r = await client.post(
        "/api/v1/query",
        json={
            "question": "What travel amount requires VP approval?",
            "wait": True,
            "failure_injection": {"category": "poor_retrieval", "fail_first": 1},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "succeeded"
    trace = await client.get(f"/api/v1/tasks/{body['task_id']}/trace")
    t = trace.json()
    assert t["corrections"], "demo injection must be visible in the trace"


async def test_research_endpoints_via_api(client):
    await client.post("/api/v1/documents", files={"file": ("policy.txt", POLICY_TXT, "text/plain")})
    r = await client.post(
        "/api/v1/evaluations/research/retrieval-comparison",
        json={"questions": ["What travel amount requires VP approval?"]},
    )
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["status"] == "succeeded"
    assert "best_strategy" in run["metrics"]

    r2 = await client.get("/api/v1/evaluations/research/retrieval-comparison")
    assert r2.status_code == 200
    assert r2.json() and r2.json()["id"] == run["id"]


async def test_login_and_rbac(client):
    from nexus.core.bootstrap import DEV_ADMIN_EMAIL, DEV_ANALYST_EMAIL, DEV_PASSWORD, ensure_default_users
    from nexus.database.session import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        created = await ensure_default_users(session)
        assert created  # first run creates users

    bad = await client.post("/api/v1/auth/login", json={"email": DEV_ADMIN_EMAIL, "password": "wrong"})
    assert bad.status_code == 403

    r = await client.post("/api/v1/auth/login", json={"email": DEV_ADMIN_EMAIL, "password": DEV_PASSWORD})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["role"] == "admin"
    assert me.json()["email"] == DEV_ADMIN_EMAIL

    # admin can read audit; analyst cannot
    audit_admin = await client.get("/api/v1/audit", headers=headers)
    assert audit_admin.status_code == 200

    r2 = await client.post("/api/v1/auth/login", json={"email": DEV_ANALYST_EMAIL, "password": DEV_PASSWORD})
    assert r2.status_code == 200
    headers_analyst = {"Authorization": f"Bearer {r2.json()['access_token']}"}
    audit_analyst = await client.get("/api/v1/audit", headers=headers_analyst)
    assert audit_analyst.status_code == 403
