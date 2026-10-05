"""self ordering switches

Revision ID: 7dea75c1555e
Revises: bfc38a2bf8fa
Create Date: 2026-10-05 22:00:00.188557

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7dea75c1555e"
down_revision: str | Sequence[str] | None = "bfc38a2bf8fa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "restaurant",
        sa.Column("accepts_qr_orders", sa.Boolean(), server_default="true", nullable=False),
    )
    op.add_column(
        "restaurant",
        sa.Column("accepts_online_orders", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("restaurant", "accepts_online_orders")
    op.drop_column("restaurant", "accepts_qr_orders")
