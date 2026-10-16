"""Dataset ingestion and profiling."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.config import settings
from nexus.core.exceptions import NotFoundError, ValidationError
from nexus.database.models import Dataset


def _read_dataframe(path: str) -> pd.DataFrame:
    ext = Path(path).suffix.lower()
    if ext == ".xlsx":
        return pd.read_excel(path)
    if ext == ".csv":
        return pd.read_csv(path)
    raise ValidationError(f"Unsupported dataset format: {ext}")


async def profile_dataset(path: str) -> dict[str, Any]:
    def _profile() -> dict[str, Any]:
        df = _read_dataframe(path)
        numeric = df.select_dtypes(include="number")
        stats: dict[str, Any] = {
            "rows": int(len(df)),
            "columns": list(df.columns),
            "dtypes": {c: str(t) for c, t in df.dtypes.items()},
            "missing": {c: int(df[c].isna().sum()) for c in df.columns},
        }
        if not numeric.empty:
            desc = numeric.describe().to_dict()
            stats["numeric_summary"] = {
                col: {k: (float(v) if isinstance(v, (int, float)) else str(v)) for k, v in m.items()}
                for col, m in desc.items()
            }
            # simple anomaly flags: columns where >5% values beyond 3 sigma
            anomalies = {}
            for col in numeric.columns:
                s = numeric[col].dropna()
                if len(s) < 8:
                    continue
                mean, std = float(s.mean()), float(s.std(ddof=0) or 1e-9)
                outliers = int((abs(s - mean) > 3 * std).sum())
                if outliers:
                    anomalies[col] = outliers
            stats["anomaly_flags"] = anomalies
        return stats

    import asyncio

    return await asyncio.to_thread(_profile)


async def ingest_dataset(
    session: AsyncSession, *, filename: str, content: bytes, name: str | None = None
) -> Dataset:
    ext = Path(filename).suffix.lower()
    if ext not in {".csv", ".xlsx"}:
        raise ValidationError("Datasets must be CSV or XLSX")
    if len(content) > settings.max_file_size_mb * 1024 * 1024:
        raise ValidationError(f"Dataset exceeds {settings.max_file_size_mb} MB")

    ds_id = str(uuid.uuid4())
    dest_dir = settings.storage_path / "datasets" / ds_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name
    dest = dest_dir / safe_name
    dest.write_bytes(content)

    dataset = Dataset(
        id=ds_id,
        name=name or safe_name,
        filename=safe_name,
        status="processing",
        storage_path=str(dest),
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)

    try:
        profile = await profile_dataset(str(dest))
        dataset.row_count = profile.get("rows", 0)
        dataset.columns_json = profile.get("columns", [])
        dataset.stats_json = profile
        dataset.status = "ready"
        dataset.error = None
    except Exception as exc:  # noqa: BLE001
        dataset.status = "failed"
        dataset.error = str(exc)[:2000]
    await session.commit()
    await session.refresh(dataset)
    return dataset


async def get_dataset(session: AsyncSession, dataset_id: str) -> Dataset:
    ds = await session.get(Dataset, dataset_id)
    if not ds:
        raise NotFoundError("Dataset not found")
    return ds
