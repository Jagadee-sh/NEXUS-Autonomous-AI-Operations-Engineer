"""Ingestion + retrieval + citation tests."""

from __future__ import annotations

from nexus.ingestion.pipeline import ingest_document
from nexus.retrieval.hybrid import RetrievalQuery, hybrid_retrieve
from tests.conftest import DEMO_SALES_CSV, POLICY_TXT


async def test_ingest_text_and_retrieve_with_real_citation(session):
    doc = await ingest_document(session, filename="policy.txt", content=POLICY_TXT)
    assert doc.status == "ready"
    assert doc.chunk_count >= 1

    hits = await hybrid_retrieve(
        session, RetrievalQuery(text="What travel amount requires VP approval?", top_k=3)
    )
    assert hits, "expected retrieval hits"
    assert any("policy.txt" in (h.filename or "") or "2,000" in h.content or "$2,000" in h.content for h in hits)
    # citation metadata is real (bound to actual chunk ids)
    assert all(h.chunk_id for h in hits)


async def test_ingest_csv_document(session):
    doc = await ingest_document(session, filename="sales.csv", content=DEMO_SALES_CSV)
    assert doc.status == "ready"


async def test_unsupported_extension_rejected(session):
    from nexus.core.exceptions import ValidationError

    try:
        await ingest_document(session, filename="evil.exe", content=b"MZ")
        raised = False
    except ValidationError:
        raised = True
    assert raised


async def test_retrieval_metadata_filter(session):
    await ingest_document(session, filename="policy.txt", content=POLICY_TXT)
    docs = await hybrid_retrieve(session, RetrievalQuery(text="churn review", top_k=5))
    filtered = await hybrid_retrieve(
        session,
        RetrievalQuery(text="churn review", top_k=5, metadata_filters={"filename": "policy.txt"}),
    )
    assert filtered
    assert all(c.filename == "policy.txt" for c in filtered)
    assert docs
