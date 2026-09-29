from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, exists, func
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship

from app.models.base import Base, TimestampMixin, str_enum
from app.models.employee import Employee
from app.models.menu import Food
from app.models.table import DiningTable
from app.models.user import User


class OrderStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PREPARING = "preparing"
    READY = "ready"
    SERVED = "served"
    PAID = "paid"
    CANCELLED = "cancelled"


# everything that still keeps a table busy
ACTIVE_STATUSES = (
    OrderStatus.PENDING,
    OrderStatus.CONFIRMED,
    OrderStatus.PREPARING,
    OrderStatus.READY,
    OrderStatus.SERVED,
)


class OrderType(StrEnum):
    DINE_IN = "dine_in"
    TAKEAWAY = "takeaway"


class OrderSource(StrEnum):
    STAFF = "staff"
    QR = "qr"
    ONLINE = "online"


class Order(TimestampMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("total >= 0", name="total_not_negative"),
        CheckConstraint("order_type <> 'dine_in' OR table_id IS NOT NULL", name="dine_in_table"),
        Index("ix_orders_status_created_at", "status", "created_at"),
        Index("ix_orders_table_id_status", "table_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_number: Mapped[str] = mapped_column(String(20), unique=True)
    order_type: Mapped[OrderType] = mapped_column(str_enum(OrderType))
    source: Mapped[OrderSource] = mapped_column(
        str_enum(OrderSource), default=OrderSource.STAFF, server_default=OrderSource.STAFF
    )
    status: Mapped[OrderStatus] = mapped_column(
        str_enum(OrderStatus), default=OrderStatus.PENDING, server_default=OrderStatus.PENDING
    )
    table_id: Mapped[int | None] = mapped_column(
        ForeignKey("dining_tables.id", ondelete="RESTRICT")
    )
    waiter_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), index=True
    )
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    customer_name: Mapped[str | None] = mapped_column(String(100))
    customer_phone: Mapped[str | None] = mapped_column(String(20))
    notes: Mapped[str | None] = mapped_column(Text)
    # money is always calculated on the server from the food prices
    subtotal: Mapped[Decimal] = mapped_column(default=Decimal(0))
    discount_total: Mapped[Decimal] = mapped_column(default=Decimal(0))
    total: Mapped[Decimal] = mapped_column(default=Decimal(0))
    cancel_reason: Mapped[str | None] = mapped_column(String(255))
    closed_at: Mapped[datetime | None]

    table: Mapped[DiningTable | None] = relationship(lazy="raise")
    waiter: Mapped[Employee | None] = relationship(lazy="raise")
    created_by: Mapped[User | None] = relationship(lazy="raise")
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="OrderItem.id",
        lazy="raise",
    )
    history: Mapped[list["OrderStatusEvent"]] = relationship(
        cascade="all, delete-orphan", order_by="OrderStatusEvent.id", lazy="raise"
    )

    @property
    def item_count(self) -> int:
        return sum(item.quantity for item in self.items)


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (CheckConstraint("quantity BETWEEN 1 AND 100", name="quantity_range"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    food_id: Mapped[int] = mapped_column(ForeignKey("foods.id", ondelete="RESTRICT"), index=True)
    # snapshot of the food at the time of ordering, later menu changes don't touch old orders
    food_name: Mapped[str] = mapped_column(String(200))
    unit_price: Mapped[Decimal]
    unit_discount: Mapped[Decimal] = mapped_column(default=Decimal(0))
    final_unit_price: Mapped[Decimal]
    quantity: Mapped[int]
    line_total: Mapped[Decimal]
    notes: Mapped[str | None] = mapped_column(String(255))

    order: Mapped[Order] = relationship(back_populates="items", lazy="raise")
    food: Mapped[Food] = relationship(lazy="raise")


class OrderStatusEvent(Base):
    """Every status change, who did it and when."""

    __tablename__ = "order_status_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[OrderStatus | None] = mapped_column(
        str_enum(OrderStatus, name="from_status")
    )
    to_status: Mapped[OrderStatus] = mapped_column(str_enum(OrderStatus, name="to_status"))
    changed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    changed_by: Mapped[User | None] = relationship(lazy="raise")


class OrderCounter(Base):
    """Last order number handed out per business day."""

    __tablename__ = "order_counters"

    business_date: Mapped[date] = mapped_column(primary_key=True)
    last_number: Mapped[int]


# a table is occupied while it has an order that isn't paid or cancelled yet
DiningTable.is_occupied = column_property(
    exists()
    .where(Order.table_id == DiningTable.id, Order.status.in_(ACTIVE_STATUSES))
    .correlate_except(Order)
)
