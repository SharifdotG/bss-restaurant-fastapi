"""index orders by closed_at

Revision ID: dae1d26b26f7
Revises: 241c50691d94
Create Date: 2026-10-01 22:25:37.739842

"""

from collections.abc import Sequence

from alembic import op

revision: str = "dae1d26b26f7"
down_revision: str | Sequence[str] | None = "241c50691d94"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_orders_status_closed_at", "orders", ["status", "closed_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_orders_status_closed_at", table_name="orders")
