"""add orders

Revision ID: f5ccebae23e4
Revises: 11fd4ff80db4
Create Date: 2026-09-29 22:46:40.869892

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f5ccebae23e4"
down_revision: str | Sequence[str] | None = "11fd4ff80db4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "order_counters",
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("last_number", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("business_date", name=op.f("pk_order_counters")),
    )
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_number", sa.String(length=20), nullable=False),
        sa.Column(
            "order_type",
            sa.Enum(
                "dine_in",
                "takeaway",
                name="ordertype",
                native_enum=False,
                create_constraint=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.Enum(
                "staff",
                "qr",
                "online",
                name="ordersource",
                native_enum=False,
                create_constraint=False,
                length=20,
            ),
            server_default="staff",
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "confirmed",
                "preparing",
                "ready",
                "served",
                "paid",
                "cancelled",
                name="orderstatus",
                native_enum=False,
                create_constraint=False,
                length=20,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("table_id", sa.Integer(), nullable=True),
        sa.Column("waiter_id", sa.Integer(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("customer_name", sa.String(length=100), nullable=True),
        sa.Column("customer_phone", sa.String(length=20), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("subtotal", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("discount_total", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("total", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("cancel_reason", sa.String(length=255), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
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
            "order_type <> 'dine_in' OR table_id IS NOT NULL", name=op.f("ck_orders_dine_in_table")
        ),
        sa.CheckConstraint(
            "order_type IN ('dine_in', 'takeaway')", name=op.f("ck_orders_ordertype")
        ),
        sa.CheckConstraint(
            "source IN ('staff', 'qr', 'online')", name=op.f("ck_orders_ordersource")
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'preparing', 'ready', 'served', 'paid', 'cancelled')",
            name=op.f("ck_orders_orderstatus"),
        ),
        sa.CheckConstraint("total >= 0", name=op.f("ck_orders_total_not_negative")),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_orders_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["table_id"],
            ["dining_tables.id"],
            name=op.f("fk_orders_table_id_dining_tables"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["waiter_id"],
            ["employees.id"],
            name=op.f("fk_orders_waiter_id_employees"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
        sa.UniqueConstraint("order_number", name=op.f("uq_orders_order_number")),
    )
    op.create_index("ix_orders_status_created_at", "orders", ["status", "created_at"], unique=False)
    op.create_index("ix_orders_table_id_status", "orders", ["table_id", "status"], unique=False)
    op.create_index(op.f("ix_orders_waiter_id"), "orders", ["waiter_id"], unique=False)
    op.create_table(
        "order_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("food_id", sa.Integer(), nullable=False),
        sa.Column("food_name", sa.String(length=200), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("unit_discount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("final_unit_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("line_total", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("notes", sa.String(length=255), nullable=True),
        sa.CheckConstraint(
            "quantity BETWEEN 1 AND 100", name=op.f("ck_order_items_quantity_range")
        ),
        sa.ForeignKeyConstraint(
            ["food_id"],
            ["foods.id"],
            name=op.f("fk_order_items_food_id_foods"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_order_items_order_id_orders"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_items")),
    )
    op.create_index(op.f("ix_order_items_food_id"), "order_items", ["food_id"], unique=False)
    op.create_index(op.f("ix_order_items_order_id"), "order_items", ["order_id"], unique=False)
    op.create_table(
        "order_status_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column(
            "from_status",
            sa.Enum(
                "pending",
                "confirmed",
                "preparing",
                "ready",
                "served",
                "paid",
                "cancelled",
                name="from_status",
                native_enum=False,
                create_constraint=False,
                length=20,
            ),
            nullable=True,
        ),
        sa.Column(
            "to_status",
            sa.Enum(
                "pending",
                "confirmed",
                "preparing",
                "ready",
                "served",
                "paid",
                "cancelled",
                name="to_status",
                native_enum=False,
                create_constraint=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("changed_by_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "from_status IN ('pending', 'confirmed', 'preparing', 'ready', 'served', 'paid', 'cancelled')",
            name=op.f("ck_order_status_events_from_status"),
        ),
        sa.CheckConstraint(
            "to_status IN ('pending', 'confirmed', 'preparing', 'ready', 'served', 'paid', 'cancelled')",
            name=op.f("ck_order_status_events_to_status"),
        ),
        sa.ForeignKeyConstraint(
            ["changed_by_id"],
            ["users.id"],
            name=op.f("fk_order_status_events_changed_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_order_status_events_order_id_orders"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_status_events")),
    )
    op.create_index(
        op.f("ix_order_status_events_order_id"), "order_status_events", ["order_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_order_status_events_order_id"), table_name="order_status_events")
    op.drop_table("order_status_events")
    op.drop_index(op.f("ix_order_items_order_id"), table_name="order_items")
    op.drop_index(op.f("ix_order_items_food_id"), table_name="order_items")
    op.drop_table("order_items")
    op.drop_index(op.f("ix_orders_waiter_id"), table_name="orders")
    op.drop_index("ix_orders_table_id_status", table_name="orders")
    op.drop_index("ix_orders_status_created_at", table_name="orders")
    op.drop_table("orders")
    op.drop_table("order_counters")
