"""Initial schema migration."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from nexus.database.base import Base
from nexus.database import models  # noqa: F401

revision = "0001_initial"
down_revision = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
