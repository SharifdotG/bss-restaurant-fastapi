"""tracking code on orders

Revision ID: bfc38a2bf8fa
Revises: e0672ca1ec27
Create Date: 2026-10-04 16:11:14.744859

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "bfc38a2bf8fa"
down_revision: str | Sequence[str] | None = "e0672ca1ec27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("tracking_code", sa.String(length=24), nullable=True))
    # existing orders get a random code too, new ones get theirs from the app
    op.execute(
        "UPDATE orders SET tracking_code = substr(replace(gen_random_uuid()::text, '-', ''), 1, 16)"
    )
    op.alter_column("orders", "tracking_code", nullable=False)
    op.create_unique_constraint(op.f("uq_orders_tracking_code"), "orders", ["tracking_code"])


def downgrade() -> None:
    op.drop_constraint(op.f("uq_orders_tracking_code"), "orders", type_="unique")
    op.drop_column("orders", "tracking_code")
