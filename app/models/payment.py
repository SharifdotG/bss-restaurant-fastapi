from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, str_enum
from app.models.user import User


class PaymentMethod(StrEnum):
    CASH = "cash"
    CARD = "card"
    # bkash, nagad, rocket and the like
    MOBILE = "mobile"


class PaymentKind(StrEnum):
    PAYMENT = "payment"
    REFUND = "refund"


class Payment(Base):
    """Money taken for an order, or given back. Amounts are always positive, `kind` says which."""

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("tendered IS NULL OR tendered >= amount", name="tendered_covers_amount"),
        Index("ix_payments_kind_created_at", "kind", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"), index=True)
    kind: Mapped[PaymentKind] = mapped_column(
        str_enum(PaymentKind), default=PaymentKind.PAYMENT, server_default=PaymentKind.PAYMENT
    )
    method: Mapped[PaymentMethod] = mapped_column(str_enum(PaymentMethod))
    amount: Mapped[Decimal]
    # cash handed over by the customer, anything above the amount goes back as change
    tendered: Mapped[Decimal | None]
    # card slip number or mobile banking transaction id
    reference: Mapped[str | None] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(String(255))
    received_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    received_by: Mapped[User | None] = relationship(lazy="raise")

    @property
    def change(self) -> Decimal:
        return self.tendered - self.amount if self.tendered is not None else Decimal(0)
