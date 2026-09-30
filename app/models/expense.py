from datetime import date
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, str_enum
from app.models.user import User


class ExpenseCategory(StrEnum):
    INGREDIENTS = "ingredients"
    UTILITIES = "utilities"
    SUPPLIES = "supplies"
    MAINTENANCE = "maintenance"
    SALARY = "salary"
    RENT = "rent"
    MARKETING = "marketing"
    OTHER = "other"


class Expense(TimestampMixin, Base):
    __tablename__ = "expenses"
    __table_args__ = (CheckConstraint("amount > 0", name="amount_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[ExpenseCategory] = mapped_column(str_enum(ExpenseCategory), index=True)
    amount: Mapped[Decimal]
    expense_date: Mapped[date] = mapped_column(index=True)
    paid_to: Mapped[str | None] = mapped_column(String(150))
    notes: Mapped[str | None] = mapped_column(Text)
    receipt_key: Mapped[str | None] = mapped_column(String(255))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    created_by: Mapped[User | None] = relationship(lazy="raise")
