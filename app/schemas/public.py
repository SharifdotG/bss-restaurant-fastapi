from datetime import datetime

from pydantic import Field, computed_field

from app.models.menu import DiscountType
from app.models.order import OrderSource, OrderStatus, OrderType
from app.schemas.common import CamelModel, Money, WithImage
from app.schemas.order import OrderItemIn
from app.schemas.restaurant import Percent
from app.schemas.user import Phone


class PublicRestaurant(CamelModel):
    name: str
    address: str | None
    phone: str | None
    email: str | None
    currency: str
    currency_symbol: str
    vat_percent: Percent
    service_charge_percent: Percent
    accepts_qr_orders: bool
    accepts_online_orders: bool


class MenuFood(WithImage):
    id: int
    name: str
    description: str | None
    price: Money
    discount_type: DiscountType
    discount_value: Money
    final_price: Money
    has_discount: bool
    is_available: bool
    is_featured: bool
    preparation_minutes: int | None


class MenuCategory(WithImage):
    id: int
    name: str
    description: str | None
    foods: list[MenuFood]


class Menu(CamelModel):
    restaurant: PublicRestaurant
    categories: list[MenuCategory]
    uncategorized: list[MenuFood]


class PublicTable(CamelModel):
    number: str
    location: str | None


class PublicOrderCreate(CamelModel):
    """Only what was ordered, prices always come from the menu."""

    items: list[OrderItemIn] = Field(min_length=1, max_length=30)
    customer_name: str | None = Field(None, max_length=100)
    customer_phone: Phone | None = None
    notes: str | None = Field(None, max_length=500)


class OnlineOrderCreate(PublicOrderCreate):
    """Takeaway from the website, the restaurant needs to know who to call."""

    customer_name: str = Field(min_length=1, max_length=100)
    customer_phone: Phone


class PublicOrderItem(CamelModel):
    food_name: str
    quantity: int
    final_unit_price: Money
    line_total: Money
    notes: str | None


class PublicStatusStep(CamelModel):
    to_status: OrderStatus
    created_at: datetime


class PublicOrder(CamelModel):
    """What a customer sees of their order, no staff names or internal ids."""

    tracking_code: str
    order_number: str
    order_type: OrderType
    source: OrderSource
    status: OrderStatus
    table: PublicTable | None
    customer_name: str | None
    items: list[PublicOrderItem]
    subtotal: Money
    discount_total: Money
    service_charge: Money
    vat: Money
    total: Money
    amount_paid: Money
    balance_due: Money
    cancel_reason: str | None
    history: list[PublicStatusStep]
    created_at: datetime

    @computed_field
    @property
    def can_cancel(self) -> bool:
        # only their own orders, and once the restaurant accepted it or money changed
        # hands the staff have to do it
        return (
            self.source != OrderSource.STAFF
            and self.status == OrderStatus.PENDING
            and self.amount_paid == 0
        )
