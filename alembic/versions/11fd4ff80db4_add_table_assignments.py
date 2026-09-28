"""add table assignments

Revision ID: 11fd4ff80db4
Revises: fb10d3c3cdc7
Create Date: 2026-09-28 22:51:16.703874

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "11fd4ff80db4"
down_revision: str | Sequence[str] | None = "fb10d3c3cdc7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "table_assignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("table_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            name=op.f("fk_table_assignments_employee_id_employees"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["table_id"],
            ["dining_tables.id"],
            name=op.f("fk_table_assignments_table_id_dining_tables"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_table_assignments")),
        sa.UniqueConstraint("table_id", "employee_id", name=op.f("uq_table_assignments_table_id")),
    )
    op.create_index(
        op.f("ix_table_assignments_employee_id"), "table_assignments", ["employee_id"], unique=False
    )
    op.create_index(
        op.f("ix_table_assignments_table_id"), "table_assignments", ["table_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_table_assignments_table_id"), table_name="table_assignments")
    op.drop_index(op.f("ix_table_assignments_employee_id"), table_name="table_assignments")
    op.drop_table("table_assignments")
