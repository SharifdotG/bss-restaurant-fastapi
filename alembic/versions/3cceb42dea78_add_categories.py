"""add categories

Revision ID: 3cceb42dea78
Revises: 7cb8078ddb50
Create Date: 2026-09-27 15:47:57.517513

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3cceb42dea78"
down_revision: str | Sequence[str] | None = "7cb8078ddb50"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("image_key", sa.String(length=255), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
    )
    op.create_index(
        "uq_categories_name_lower", "categories", [sa.literal_column("lower(name)")], unique=True
    )


def downgrade() -> None:
    op.drop_index("uq_categories_name_lower", table_name="categories")
    op.drop_table("categories")
