from decimal import Decimal

from sqlalchemy import CheckConstraint, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

RESTAURANT_ID = 1

Percent = Numeric(5, 2)


class Restaurant(TimestampMixin, Base):
    """Details printed on bills and the rates used to calculate them. There is only one row."""

    __tablename__ = "restaurant"
    __table_args__ = (
        CheckConstraint(f"id = {RESTAURANT_ID}", name="single_row"),
        CheckConstraint("vat_percent BETWEEN 0 AND 100", name="vat_range"),
        CheckConstraint("service_charge_percent BETWEEN 0 AND 100", name="service_charge_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(150), default="My Restaurant")
    address: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(255))
    # VAT registration number (BIN in Bangladesh), printed on receipts when set
    tax_id: Mapped[str | None] = mapped_column(String(50))
    currency: Mapped[str] = mapped_column(String(3), default="BDT")
    currency_symbol: Mapped[str] = mapped_column(String(5), default="৳")
    vat_percent: Mapped[Decimal] = mapped_column(Percent, default=Decimal(0))
    # only charged on dine in orders
    service_charge_percent: Mapped[Decimal] = mapped_column(Percent, default=Decimal(0))
    receipt_footer: Mapped[str | None] = mapped_column(String(500))
    # customers ordering by themselves, from the qr code on the table or the website
    accepts_qr_orders: Mapped[bool] = mapped_column(default=True, server_default="true")
    accepts_online_orders: Mapped[bool] = mapped_column(default=False, server_default="false")
