"""vat and service charge on orders

Revision ID: 307671d03fed
Revises: e94d78e05686
Create Date: 2026-10-03 15:24:25.628432

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "307671d03fed"
down_revision: str | Sequence[str] | None = "e94d78e05686"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "service_charge_rate",
            sa.Numeric(precision=5, scale=2),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "orders",
        sa.Column("vat_rate", sa.Numeric(precision=5, scale=2), server_default="0", nullable=False),
    )
    op.add_column(
        "orders",
        sa.Column(
            "service_charge", sa.Numeric(precision=12, scale=2), server_default="0", nullable=False
        ),
    )
    op.add_column(
        "orders",
        sa.Column("vat", sa.Numeric(precision=12, scale=2), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("orders", "vat")
    op.drop_column("orders", "service_charge")
    op.drop_column("orders", "vat_rate")
    op.drop_column("orders", "service_charge_rate")
