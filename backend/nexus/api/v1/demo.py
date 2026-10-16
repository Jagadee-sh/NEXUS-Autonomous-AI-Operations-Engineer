"""Demo data endpoint: load synthetic demo documents/datasets via API."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.api.deps import AuthContext, require_role
from nexus.config import settings
from nexus.database.session import get_session
from nexus.ingestion.pipeline import ingest_document
from nexus.logging_config import get_logger
from nexus.services.dataset_service import ingest_dataset

log = get_logger("nexus.demo")
router = APIRouter(prefix="/demo", tags=["demo"])

DOC_NAMES = [
    "annual_report.pdf",
    "business_policy.pdf",
    "product_documentation.pdf",
    "onboarding_playbook.txt",
]
DATA_NAMES = ["sales.csv", "customers.csv", "expenses.csv", "support_tickets.csv"]


def _repo_root() -> Path:
    # backend/nexus/api/v1/demo.py → repo root is 3 levels up
    return Path(settings.storage_dir).resolve().parents[0]


@router.post("/load")
async def load_demo(
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[AuthContext, Depends(require_role("analyst"))],
) -> dict:
    root = _repo_root()
    candidates = [root, root.parent, Path.cwd(), Path.cwd().parent]
    data_dir = next((c / "data" / "demo" for c in candidates if (c / "data" / "demo").is_dir()), None)
    doc_dir = next((c / "documents" / "demo" for c in candidates if (c / "documents" / "demo").is_dir()), None)
    if not data_dir or not doc_dir:
        # generate on the fly
        import sys

        script_dir = next((c / "scripts" for c in candidates if (c / "scripts" / "generate_demo_data.py").is_file()), None)
        if not script_dir:
            return {"documents": 0, "datasets": 0, "error": "demo source not found; run scripts/generate_demo_data.py"}
        sys.path.insert(0, str(script_dir.parent))
        from scripts.generate_demo_data import main as generate

        generate()
        data_dir = next(c / "data" / "demo" for c in candidates if (c / "data" / "demo").is_dir())
        doc_dir = next(c / "documents" / "demo" for c in candidates if (c / "documents" / "demo").is_dir())

    docs = 0
    datasets = 0
    for name in DOC_NAMES:
        p = doc_dir / name
        if p.exists():
            try:
                await ingest_document(session, filename=name, content=p.read_bytes())
                docs += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("demo doc %s failed: %s", name, exc)
    for name in DATA_NAMES:
        p = data_dir / name
        if p.exists():
            try:
                ds = await ingest_dataset(
                    session, filename=name, content=p.read_bytes(), name=p.stem.replace("_", " ").title()
                )
                if ds.status == "ready":
                    datasets += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("demo dataset %s failed: %s", name, exc)
    return {"documents": docs, "datasets": datasets}
