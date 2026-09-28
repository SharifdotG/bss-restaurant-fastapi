"""add employees

Revision ID: fb10d3c3cdc7
Revises: 8a6213a6ac2c
Create Date: 2026-09-28 22:29:23.977323

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fb10d3c3cdc7"
down_revision: str | Sequence[str] | None = "8a6213a6ac2c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "employees",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("designation", sa.String(length=100), nullable=False),
        sa.Column("join_date", sa.Date(), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column(
            "gender",
            sa.Enum(
                "male",
                "female",
                "other",
                name="gender",
                native_enum=False,
                create_constraint=False,
                length=20,
            ),
            nullable=True,
        ),
        sa.Column("nid", sa.String(length=30), nullable=True),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("father_name", sa.String(length=100), nullable=True),
        sa.Column("mother_name", sa.String(length=100), nullable=True),
        sa.Column("spouse_name", sa.String(length=100), nullable=True),
        sa.Column("monthly_salary", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("image_key", sa.String(length=255), nullable=True),
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
        sa.CheckConstraint(
            "gender IN ('male', 'female', 'other')", name=op.f("ck_employees_gender")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_employees_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_employees")),
        sa.UniqueConstraint("nid", name=op.f("uq_employees_nid")),
        sa.UniqueConstraint("phone", name=op.f("uq_employees_phone")),
        sa.UniqueConstraint("user_id", name=op.f("uq_employees_user_id")),
    )


def downgrade() -> None:
    op.drop_table("employees")
