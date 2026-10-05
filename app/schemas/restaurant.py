from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import EmailStr, Field, PlainSerializer

from app.schemas.common import CamelModel
from app.schemas.user import Phone

Percent = Annotated[
    Decimal,
    Field(ge=0, le=100, max_digits=5, decimal_places=2),
    PlainSerializer(float, return_type=float, when_used="json"),
]


class RestaurantOut(CamelModel):
    name: str
    address: str | None
    phone: str | None
    email: str | None
    tax_id: str | None
    currency: str
    currency_symbol: str
    vat_percent: Percent
    service_charge_percent: Percent
    receipt_footer: str | None
    accepts_qr_orders: bool
    accepts_online_orders: bool
    updated_at: datetime


class RestaurantUpdate(CamelModel):
    name: str | None = Field(None, min_length=1, max_length=150)
    address: str | None = Field(None, max_length=255)
    phone: Phone | None = None
    email: EmailStr | None = None
    tax_id: str | None = Field(None, max_length=50, description="VAT registration number (BIN)")
    currency: str | None = Field(None, pattern=r"^[A-Z]{3}$", description="ISO code, e.g. BDT")
    currency_symbol: str | None = Field(None, min_length=1, max_length=5)
    vat_percent: Percent | None = None
    service_charge_percent: Percent | None = Field(None, description="Only for dine in orders")
    receipt_footer: str | None = Field(None, max_length=500)
    accepts_qr_orders: bool | None = None
    accepts_online_orders: bool | None = Field(None, description="Takeaway orders from the website")
