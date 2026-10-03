"""add payments

Revision ID: e0672ca1ec27
Revises: 307671d03fed
Create Date: 2026-10-03 16:11:06.109063

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e0672ca1ec27"
down_revision: str | Sequence[str] | None = "307671d03fed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "payment",
                "refund",
                name="paymentkind",
                native_enum=False,
                create_constraint=False,
                length=20,
            ),
            server_default="payment",
            nullable=False,
        ),
        sa.Column(
            "method",
            sa.Enum(
                "cash",
                "card",
                "mobile",
                name="paymentmethod",
                native_enum=False,
                create_constraint=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("tendered", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("reference", sa.String(length=100), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("received_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('payment', 'refund')", name=op.f("ck_payments_paymentkind")),
        sa.CheckConstraint(
            "method IN ('cash', 'card', 'mobile')", name=op.f("ck_payments_paymentmethod")
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_payments_amount_positive")),
        sa.CheckConstraint(
            "tendered IS NULL OR tendered >= amount",
            name=op.f("ck_payments_tendered_covers_amount"),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_payments_order_id_orders"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["received_by_id"],
            ["users.id"],
            name=op.f("fk_payments_received_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payments")),
    )
    op.create_index("ix_payments_kind_created_at", "payments", ["kind", "created_at"], unique=False)
    op.create_index(op.f("ix_payments_order_id"), "payments", ["order_id"], unique=False)
    op.add_column(
        "orders",
        sa.Column(
            "amount_paid", sa.Numeric(precision=12, scale=2), server_default="0", nullable=False
        ),
    )
    op.create_check_constraint(
        op.f("ck_orders_amount_paid_not_negative"), "orders", "amount_paid >= 0"
    )
    # orders closed before payments existed were paid in full
    op.execute("UPDATE orders SET amount_paid = total WHERE status = 'paid'")


def downgrade() -> None:
    op.drop_constraint(op.f("ck_orders_amount_paid_not_negative"), "orders", type_="check")
    op.drop_column("orders", "amount_paid")
    op.drop_index(op.f("ix_payments_order_id"), table_name="payments")
    op.drop_index("ix_payments_kind_created_at", table_name="payments")
    op.drop_table("payments")
