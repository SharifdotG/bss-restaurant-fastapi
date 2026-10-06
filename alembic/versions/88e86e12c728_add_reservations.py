"""add reservations

Revision ID: 88e86e12c728
Revises: c4d75985d45d
Create Date: 2026-10-06 22:46:56.240667

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "88e86e12c728"
down_revision: str | Sequence[str] | None = "c4d75985d45d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # gist index on a plain integer column, for the no double booking constraint
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_table(
        "reservations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tracking_code", sa.String(length=24), nullable=False),
        sa.Column(
            "source",
            sa.Enum(
                "staff",
                "online",
                name="reservationsource",
                native_enum=False,
                create_constraint=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "requested",
                "confirmed",
                "seated",
                "completed",
                "cancelled",
                "declined",
                "no_show",
                name="reservationstatus",
                native_enum=False,
                create_constraint=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("table_id", sa.Integer(), nullable=True),
        sa.Column("party_size", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("customer_name", sa.String(length=100), nullable=False),
        sa.Column("customer_phone", sa.String(length=20), nullable=False),
        sa.Column("customer_email", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("cancel_reason", sa.String(length=255), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
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
        postgresql.ExcludeConstraint(
            (sa.column("table_id"), "="),
            (sa.text("tstzrange(starts_at, ends_at)"), "&&"),
            where=sa.text("status IN ('confirmed', 'seated')"),
            using="gist",
            name="ex_reservations_no_double_booking",
        ),
        sa.CheckConstraint(
            "source IN ('staff', 'online')", name=op.f("ck_reservations_reservationsource")
        ),
        sa.CheckConstraint(
            "status IN ('requested', 'confirmed', 'seated', 'completed', 'cancelled', 'declined', 'no_show')",
            name=op.f("ck_reservations_reservationstatus"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('confirmed', 'seated') OR table_id IS NOT NULL",
            name=op.f("ck_reservations_confirmed_has_table"),
        ),
        sa.CheckConstraint("ends_at > starts_at", name=op.f("ck_reservations_ends_after_start")),
        sa.CheckConstraint(
            "party_size BETWEEN 1 AND 50", name=op.f("ck_reservations_party_size_range")
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_reservations_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["table_id"],
            ["dining_tables.id"],
            name=op.f("fk_reservations_table_id_dining_tables"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reservations")),
        sa.UniqueConstraint("tracking_code", name=op.f("uq_reservations_tracking_code")),
    )
    op.create_index(
        op.f("ix_reservations_customer_phone"), "reservations", ["customer_phone"], unique=False
    )
    op.create_index(
        "ix_reservations_status_starts_at", "reservations", ["status", "starts_at"], unique=False
    )
    op.create_index(op.f("ix_reservations_table_id"), "reservations", ["table_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_reservations_table_id"), table_name="reservations")
    op.drop_index("ix_reservations_status_starts_at", table_name="reservations")
    op.drop_index(op.f("ix_reservations_customer_phone"), table_name="reservations")
    op.drop_table("reservations")
