"""add dining tables

Revision ID: 8a6213a6ac2c
Revises: 622a1db61e8f
Create Date: 2026-09-28 22:02:41.668372

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8a6213a6ac2c"
down_revision: str | Sequence[str] | None = "622a1db61e8f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dining_tables",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("number", sa.String(length=20), nullable=False),
        sa.Column("seats", sa.Integer(), nullable=False),
        sa.Column("location", sa.String(length=100), nullable=True),
        sa.Column("image_key", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("qr_token", sa.String(length=32), nullable=False),
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
        sa.CheckConstraint("seats BETWEEN 1 AND 50", name=op.f("ck_dining_tables_seats_range")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dining_tables")),
        sa.UniqueConstraint("qr_token", name=op.f("uq_dining_tables_qr_token")),
    )
    op.create_index(
        "uq_dining_tables_number_lower",
        "dining_tables",
        [sa.literal_column("lower(number)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_dining_tables_number_lower", table_name="dining_tables")
    op.drop_table("dining_tables")
