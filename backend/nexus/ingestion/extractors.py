"""Format extractors: PDF, DOCX, TXT, MD, CSV, XLSX."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path

from nexus.core.exceptions import ValidationError

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".csv", ".xlsx"}
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/csv",
    "application/octet-stream",
}


@dataclass
class ExtractedSegment:
    text: str
    page: int | None = None
    section: str | None = None
    metadata: dict = field(default_factory=dict)


def validate_upload(filename: str, content_type: str, size_bytes: int, max_mb: int) -> None:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(f"Unsupported file type '{ext}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}")
    if size_bytes > max_mb * 1024 * 1024:
        raise ValidationError(f"File exceeds maximum size of {max_mb} MB")
    if size_bytes == 0:
        raise ValidationError("Empty file")
    if content_type and content_type not in ALLOWED_CONTENT_TYPES:
        # extension already validated; warn-level mismatch tolerated for octet-stream
        if not content_type.startswith("text/"):
            raise ValidationError(f"Disallowed content type: {content_type}")


def extract_file(path: Path, filename: str) -> list[ExtractedSegment]:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return extract_pdf(path)
    if ext == ".docx":
        return extract_docx(path)
    if ext in {".txt", ".md"}:
        return extract_text(path)
    if ext == ".csv":
        return extract_csv(path)
    if ext == ".xlsx":
        return extract_xlsx(path)
    raise ValidationError(f"No extractor for {ext}")


def extract_pdf(path: Path) -> list[ExtractedSegment]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    segments: list[ExtractedSegment] = []
    for i, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            segments.append(ExtractedSegment(text=text, page=i, section=f"Page {i}"))
    if not segments:
        raise ValidationError("PDF contained no extractable text (scanned images need OCR — not in MVP)")
    return segments


def extract_docx(path: Path) -> list[ExtractedSegment]:
    import docx

    document = docx.Document(str(path))
    paragraphs = [p.text.strip() for p in document.paragraphs if p.text and p.text.strip()]
    if not paragraphs:
        raise ValidationError("DOCX contained no text")
    text = "\n".join(paragraphs)
    return [ExtractedSegment(text=text, section=document.core_properties.title or "document")]


def extract_text(path: Path) -> list[ExtractedSegment]:
    raw = path.read_bytes()
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValidationError("Could not decode text file")
    text = text.strip()
    if not text:
        raise ValidationError("Text file is empty")
    return [ExtractedSegment(text=text)]


def extract_csv(path: Path) -> list[ExtractedSegment]:
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        raise ValidationError("CSV is empty")
    header = rows[0]
    lines = [", ".join(header)]
    for row in rows[1:]:
        lines.append(", ".join(f"{h}={v}" for h, v in zip(header, row, strict=False)))
    return [ExtractedSegment(text="\n".join(lines[:500]), section="tabular", metadata={"rows": len(rows) - 1})]


def extract_xlsx(path: Path) -> list[ExtractedSegment]:
    import openpyxl

    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    segments: list[ExtractedSegment] = []
    for sheet in wb.worksheets:
        rows_iter = sheet.iter_rows(values_only=True)
        try:
            header_row = next(rows_iter)
        except StopIteration:
            continue
        header = [str(h) if h is not None else f"col{i}" for i, h in enumerate(header_row)]
        lines = [", ".join(header)]
        for row in rows_iter:
            lines.append(", ".join(f"{h}={v}" for h, v in zip(header, row, strict=False)))
            if len(lines) > 501:
                break
        segments.append(
            ExtractedSegment(text="\n".join(lines), section=sheet.title, metadata={"sheet": sheet.title})
        )
    wb.close()
    if not segments:
        raise ValidationError("XLSX contained no sheets with data")
    return segments
