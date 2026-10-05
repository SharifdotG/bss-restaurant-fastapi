"""reservation settings

Revision ID: c4d75985d45d
Revises: 7dea75c1555e
Create Date: 2026-10-05 23:42:33.883048

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4d75985d45d"
down_revision: str | Sequence[str] | None = "7dea75c1555e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "restaurant",
        sa.Column("accepts_reservations", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "restaurant",
        sa.Column(
            "auto_confirm_reservations", sa.Boolean(), server_default="false", nullable=False
        ),
    )
    op.add_column(
        "restaurant",
        sa.Column("reservation_minutes", sa.Integer(), server_default="90", nullable=False),
    )
    op.add_column(
        "restaurant", sa.Column("opens_at", sa.Time(), server_default="11:00", nullable=False)
    )
    op.add_column(
        "restaurant", sa.Column("closes_at", sa.Time(), server_default="23:00", nullable=False)
    )
    op.create_check_constraint(
        op.f("ck_restaurant_reservation_minutes_range"),
        "restaurant",
        "reservation_minutes BETWEEN 15 AND 480",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_restaurant_reservation_minutes_range"), "restaurant", type_="check")
    op.drop_column("restaurant", "closes_at")
    op.drop_column("restaurant", "opens_at")
    op.drop_column("restaurant", "reservation_minutes")
    op.drop_column("restaurant", "auto_confirm_reservations")
    op.drop_column("restaurant", "accepts_reservations")
