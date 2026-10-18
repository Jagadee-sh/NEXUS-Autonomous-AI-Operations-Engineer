"""Add structured execution events for NEXUS Omega observation."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0002_execution_events"
down_revision = "0001_initial"


def upgrade() -> None:
    op.create_table(
        "execution_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("trace_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False, default=0),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("component", sa.String(length=100), nullable=False, default=""),
        sa.Column("status", sa.String(length=30), nullable=False, default="success"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False, default=0),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_execution_events_task_id", "execution_events", ["task_id"])
    op.create_index("ix_execution_events_trace_id", "execution_events", ["trace_id"])
    op.create_index(
        "ix_execution_events_trace_sequence",
        "execution_events",
        ["trace_id", "sequence"],
    )


def downgrade() -> None:
    op.drop_index("ix_execution_events_trace_sequence", table_name="execution_events")
    op.drop_index("ix_execution_events_trace_id", table_name="execution_events")
    op.drop_index("ix_execution_events_task_id", table_name="execution_events")
    op.drop_table("execution_events")
