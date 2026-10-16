"""Seed the local NEXUS environment with demo datasets, documents, and an evaluation set.

Usage (from repo root, backend installed):
    cd backend && python ../scripts/seed_demo_data.py
or:
    python scripts/seed_demo_data.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from scripts.generate_demo_data import main as generate  # noqa: E402


async def _seed() -> None:
    from nexus.core.bootstrap import ensure_default_users
    from nexus.database.models import EvaluationDataset
    from nexus.database.session import get_session_factory, init_db
    from nexus.ingestion.pipeline import ingest_document
    from nexus.services.dataset_service import ingest_dataset

    generate()
    await init_db()
    factory = get_session_factory()
    data_dir = ROOT / "data" / "demo"
    doc_dir = ROOT / "documents" / "demo"

    async with factory() as session:
        created_users = await ensure_default_users(session)
        if created_users:
            print(f"users created: {', '.join(created_users)} (password: see README / NEXUS_*_PASSWORD)")
        for csv_name in ["sales.csv", "customers.csv", "expenses.csv", "support_tickets.csv"]:
            path = data_dir / csv_name
            ds = await ingest_dataset(
                session, filename=csv_name, content=path.read_bytes(), name=path.stem.replace("_", " ").title()
            )
            print(f"dataset {ds.name}: {ds.status} rows={ds.row_count}")

        for doc_name in [
            "annual_report.pdf",
            "business_policy.pdf",
            "product_documentation.pdf",
            "onboarding_playbook.txt",
        ]:
            path = doc_dir / doc_name
            doc = await ingest_document(session, filename=doc_name, content=path.read_bytes())
            print(f"document {doc.filename}: {doc.status} chunks={doc.chunk_count}")

        from sqlalchemy import select

        existing = (
            await session.execute(select(EvaluationDataset).where(EvaluationDataset.name == "Demo QA"))
        ).scalars().first()
        if not existing:
            session.add(
                EvaluationDataset(
                    name="Demo QA",
                    description="Deterministic evaluation set for the local provider",
                    items=[
                        {
                            "id": "q3-profitability",
                            "question": (
                                "Analyze why profitability declined in Q3. Compare Q2 and Q3, identify the top "
                                "three contributing factors, verify using company documents, and recommend three actions."
                            ),
                            "expected_answer": "Q3 profitability declined due to cloud infrastructure cost overruns, professional services spend, and SMB churn. Margin fell.",
                            "expected_sources": ["annual_report.pdf"],
                            "expected_keywords": ["Q3", "margin", "churn", "infrastructure"],
                        },
                        {
                            "id": "travel-policy",
                            "question": "What is the travel policy threshold that requires VP approval according to company documents?",
                            "expected_answer": "Travel above $2,000 requires VP approval.",
                            "expected_sources": ["business_policy.pdf"],
                            "expected_keywords": ["2000", "VP", "approval"],
                        },
                    ],
                )
            )
            await session.commit()
            print("evaluation dataset 'Demo QA' created")


def main() -> None:
    asyncio.run(_seed())


if __name__ == "__main__":
    main()
