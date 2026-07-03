"""add alert ntfy topic

Revision ID: 0002_add_alert_ntfy_topic
Revises: 0001_initial
Create Date: 2026-07-02 00:00:01.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_add_alert_ntfy_topic"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("printers", sa.Column("alert_ntfy_topic", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("printers", "alert_ntfy_topic")
