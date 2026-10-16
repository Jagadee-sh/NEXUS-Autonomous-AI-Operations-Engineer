"""Generate realistic synthetic enterprise demo data (CSV + simple PDF/DOCX/TXT docs)."""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "demo"
DOC_DIR = ROOT / "documents" / "demo"


def _write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def gen_sales(path: Path, seed: int = 42) -> None:
    rng = random.Random(seed)
    regions = ["North", "South", "East", "West"]
    rows = []
    start = date(2024, 1, 1)
    for day_offset in range(365):
        d = start + timedelta(days=day_offset)
        quarter = (d.month - 1) // 3 + 1
        # Q3 deliberate margin pressure: higher COGS ratio and marketing spend
        base = 8000 + rng.uniform(-800, 800)
        if quarter == 3:
            revenue = base * 0.95  # slight revenue dip
            cogs_ratio = 0.72
            marketing = 2200
        elif quarter == 2:
            revenue = base * 1.05
            cogs_ratio = 0.58
            marketing = 1400
        else:
            revenue = base
            cogs_ratio = 0.60
            marketing = 1500
        region = rng.choice(regions)
        revenue = round(revenue, 2)
        cogs = round(revenue * cogs_ratio, 2)
        opex = round(revenue * 0.12 + marketing * 0.1, 2)
        rows.append([d.isoformat(), region, revenue, cogs, opex, round(marketing / 7, 2), quarter])
    _write_csv(
        path,
        ["date", "region", "revenue", "cogs", "operating_expenses", "marketing_spend", "quarter"],
        rows,
    )


def gen_customers(path: Path, seed: int = 7) -> None:
    rng = random.Random(seed)
    segments = ["SMB", "Mid-Market", "Enterprise"]
    rows = []
    for i in range(1, 401):
        signup = date(2022, 1, 1) + timedelta(days=rng.randint(0, 800))
        segment = rng.choice(segments)
        # Q3 churn spike for SMB
        churned = False
        churn_date = ""
        churn_reason = ""
        if rng.random() < (0.22 if segment == "SMB" else 0.08):
            churned = True
            q = rng.choice([1, 2, 3, 3, 3, 4])  # bias Q3
            month = {1: 2, 2: 5, 3: rng.choice([7, 8, 9]), 4: 11}[q]
            churn_date = date(2024, month, rng.randint(1, 28)).isoformat()
            churn_reason = rng.choice(
                ["price", "onboarding friction", "support response time", "competitor", "missing feature"]
            )
        rows.append(
            [
                f"CUST-{i:04d}",
                segment,
                signup.isoformat(),
                rng.randint(1, 36),
                churned,
                churn_date,
                churn_reason,
            ]
        )
    _write_csv(
        path,
        ["customer_id", "segment", "signup_date", "tenure_months", "churned", "churn_date", "churn_reason"],
        rows,
    )


def gen_expenses(path: Path, seed: int = 11) -> None:
    rng = random.Random(seed)
    cats = ["Salaries", "Cloud Infrastructure", "Marketing", "Travel", "Support Tooling", "Professional Services"]
    rows = []
    for month in range(1, 13):
        for cat in cats:
            base = {
                "Salaries": 180000,
                "Cloud Infrastructure": 42000,
                "Marketing": 38000,
                "Travel": 12000,
                "Support Tooling": 9000,
                "Professional Services": 15000,
            }[cat]
            if month in (7, 8, 9) and cat in {"Cloud Infrastructure", "Professional Services", "Marketing"}:
                base *= 1.35  # Q3 cost overrun drivers
            amount = round(base * rng.uniform(0.92, 1.08), 2)
            rows.append([f"2024-{month:02d}", cat, amount, "USD"])
    _write_csv(path, ["month", "category", "amount", "currency"], rows)


def gen_tickets(path: Path, seed: int = 3) -> None:
    rng = random.Random(seed)
    topics = ["billing", "outage", "onboarding", "feature-request", "bug", "integration"]
    rows = []
    for i in range(1, 601):
        created = date(2024, 1, 1) + timedelta(days=rng.randint(0, 364))
        q = (created.month - 1) // 3 + 1
        priority = rng.choice(["low", "medium", "high", "critical"])
        if q == 3 and rng.random() < 0.35:
            priority = rng.choice(["high", "critical"])
        rows.append(
            [
                f"TKT-{i:05d}",
                created.isoformat(),
                rng.choice(topics),
                priority,
                rng.randint(1, 72),
                "resolved" if rng.random() > 0.12 else "open",
            ]
        )
    _write_csv(path, ["ticket_id", "created_at", "topic", "priority", "first_response_hours", "status"], rows)


def _minimal_pdf(text_lines: list[str], path: Path) -> None:
    """Write a tiny valid PDF with Helvetica text (no external deps)."""
    escape = lambda s: s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")  # noqa: E731
    content_lines = ["BT /F1 11 Tf 50 780 Td 14 TL"]
    for i, line in enumerate(text_lines):
        if i == 0:
            content_lines.append(f"({escape(line)}) Tj")
        else:
            content_lines.append(f"T* ({escape(line)}) Tj")
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode("latin-1", errors="replace")

    objects = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>"
    )
    objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects)+1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n"
    ).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out))


def gen_documents() -> None:
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    _minimal_pdf(
        [
            "NEXUS Industries — Annual Report 2024",
            "",
            "Executive Overview:",
            "Full-year revenue grew 4% year over year. However, profitability declined in Q3 2024.",
            "Gross margin fell from 41.8% in Q2 to 33.1% in Q3.",
            "Primary drivers identified by management:",
            "1) Cloud infrastructure costs rose 35% due to an unplanned migration and over-provisioning.",
            "2) Professional services spend increased 35% for emergency implementation support.",
            "3) SMB customer churn spiked to 22% in Q3, driven mainly by onboarding friction and support response times.",
            "Marketing spend was elevated but delivered flat pipeline, reducing ROI.",
            "",
            "Outlook:",
            "Management has launched a cost-discipline program and an onboarding overhaul targeting Q4 recovery.",
            "Risk factors include competitive pricing pressure and lingering infrastructure inefficiencies.",
        ],
        DOC_DIR / "annual_report.pdf",
    )
    _minimal_pdf(
        [
            "NEXUS Industries — Business Policy Manual",
            "",
            "Travel Policy: All travel above $2,000 requires VP approval.",
            "Expense Policy: Monthly cloud spend variance above 15% must be reviewed by FinOps.",
            "Support SLA: Critical tickets require first response within 4 business hours.",
            "Churn Review: Any segment with monthly churn above 10% triggers a customer success review.",
            "Procurement: Professional services engagements above $50,000 need CFO sign-off.",
        ],
        DOC_DIR / "business_policy.pdf",
    )
    _minimal_pdf(
        [
            "Product Documentation — Analytics Platform",
            "",
            "The Analytics Platform provides dashboards, scheduled reports, and anomaly alerts.",
            "Known limitation: anomaly detection requires at least 8 periods of history.",
            "Q3 release introduced a new billing engine; a subset of SMB customers experienced invoice confusion,",
            "which support tickets indicate contributed to churn complaints in August and September.",
            "Integration with the data warehouse is read-only by design.",
        ],
        DOC_DIR / "product_documentation.pdf",
    )

    (DOC_DIR / "onboarding_playbook.txt").write_text(
        """NEXUS Onboarding Playbook

Stage 1: Kickoff within 3 business days of signup.
Stage 2: Data connection within 10 business days.
Stage 3: First value milestone within 30 days.

Q3 retrospective note: the new billing engine caused invoice confusion for SMB customers.
Support response times degraded during the cloud migration, increasing first-response hours.
Customer Success recommends dedicated onboarding concierge for SMB during major releases.
""",
        encoding="utf-8",
    )


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    gen_sales(DATA_DIR / "sales.csv")
    gen_customers(DATA_DIR / "customers.csv")
    gen_expenses(DATA_DIR / "expenses.csv")
    gen_tickets(DATA_DIR / "support_tickets.csv")
    gen_documents()
    print(f"Demo data written to {DATA_DIR} and {DOC_DIR}")


if __name__ == "__main__":
    main()
