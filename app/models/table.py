import secrets

from sqlalchemy import CheckConstraint, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


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


Index("uq_dining_tables_number_lower", func.lower(DiningTable.number), unique=True)
