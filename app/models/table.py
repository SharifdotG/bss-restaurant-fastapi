import secrets
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.employee import Employee


def new_qr_token() -> str:
    return secrets.token_urlsafe(16)


class DiningTable(TimestampMixin, Base):
    # "table" is a reserved word in sql, hence the name
    __tablename__ = "dining_tables"
    __table_args__ = (CheckConstraint("seats BETWEEN 1 AND 50", name="seats_range"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(20))
    seats: Mapped[int]
    location: Mapped[str | None] = mapped_column(String(100))
    image_key: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")
    # printed as a QR code on the table, lets customers order without logging in
    qr_token: Mapped[str] = mapped_column(String(32), unique=True, default=new_qr_token)

    employees: Mapped[list[Employee]] = relationship(
        secondary="table_assignments",
        order_by=Employee.first_name,
        viewonly=True,
        lazy="raise",
        back_populates="tables",
    )


class TableAssignment(Base):
    """Which employees serve which tables."""

    __tablename__ = "table_assignments"
    __table_args__ = (UniqueConstraint("table_id", "employee_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    table_id: Mapped[int] = mapped_column(
        ForeignKey("dining_tables.id", ondelete="CASCADE"), index=True
    )
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


Index("uq_dining_tables_number_lower", func.lower(DiningTable.number), unique=True)
