"""add restaurant settings

Revision ID: e94d78e05686
Revises: dae1d26b26f7
Create Date: 2026-10-03 14:43:36.751970

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e94d78e05686"
down_revision: str | Sequence[str] | None = "dae1d26b26f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "restaurant",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("tax_id", sa.String(length=50), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("currency_symbol", sa.String(length=5), nullable=False),
        sa.Column("vat_percent", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("service_charge_percent", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("receipt_footer", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name=op.f("ck_restaurant_single_row")),
        sa.CheckConstraint(
            "service_charge_percent BETWEEN 0 AND 100",
            name=op.f("ck_restaurant_service_charge_range"),
        ),
        sa.CheckConstraint("vat_percent BETWEEN 0 AND 100", name=op.f("ck_restaurant_vat_range")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_restaurant")),
    )


def downgrade() -> None:
    op.drop_table("restaurant")
