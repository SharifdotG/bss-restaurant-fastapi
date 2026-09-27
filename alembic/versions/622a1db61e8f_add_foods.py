"""add foods

Revision ID: 622a1db61e8f
Revises: 3cceb42dea78
Create Date: 2026-09-27 16:42:42.775224

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "622a1db61e8f"
down_revision: str | Sequence[str] | None = "3cceb42dea78"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "foods",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "discount_type",
            sa.Enum(
                "none",
                "percentage",
                "flat",
                name="discounttype",
                native_enum=False,
                create_constraint=False,
                length=20,
            ),
            server_default="none",
            nullable=False,
        ),
        sa.Column(
            "discount_value", sa.Numeric(precision=12, scale=2), server_default="0", nullable=False
        ),
        sa.Column("is_available", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("is_featured", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("preparation_minutes", sa.Integer(), nullable=True),
        sa.Column("image_key", sa.String(length=255), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "discount_type <> 'flat' OR discount_value <= price",
            name=op.f("ck_foods_flat_max_price"),
        ),
        sa.CheckConstraint(
            "discount_type <> 'percentage' OR discount_value <= 100",
            name=op.f("ck_foods_percentage_max_100"),
        ),
        sa.CheckConstraint(
            "discount_type IN ('none', 'percentage', 'flat')", name=op.f("ck_foods_discounttype")
        ),
        sa.CheckConstraint("discount_value >= 0", name=op.f("ck_foods_discount_not_negative")),
        sa.CheckConstraint("price >= 0", name=op.f("ck_foods_price_not_negative")),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_foods_category_id_categories"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_foods")),
    )
    op.create_index(op.f("ix_foods_category_id"), "foods", ["category_id"], unique=False)
    op.create_index(
        "uq_foods_name_lower",
        "foods",
        [sa.literal_column("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_foods_name_lower", table_name="foods", postgresql_where=sa.text("deleted_at IS NULL")
    )
    op.drop_index(op.f("ix_foods_category_id"), table_name="foods")
    op.drop_table("foods")
