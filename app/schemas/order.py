from datetime import date, datetime
from typing import Self

from pydantic import Field, model_validator

from app.models.order import OrderSource, OrderStatus, OrderType
from app.schemas.common import CamelModel, ListParams, Money
from app.schemas.user import Phone


class OrderItemIn(CamelModel):
    food_id: int
    quantity: int = Field(ge=1, le=100)
    notes: str | None = Field(None, max_length=255, description="e.g. no onions")


class OrderCreate(CamelModel):
    """Prices are never sent by the client, they come from the menu."""

    order_type: OrderType = OrderType.DINE_IN
    table_id: int | None = None
    waiter_id: int | None = Field(None, description="Defaults to the employee placing the order")
    customer_name: str | None = Field(None, max_length=100)
    customer_phone: Phone | None = None
    notes: str | None = Field(None, max_length=1000)
    items: list[OrderItemIn] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def _check_table(self) -> Self:
        if self.order_type == OrderType.DINE_IN and self.table_id is None:
            raise ValueError("dine in orders need a table")
        if self.order_type == OrderType.TAKEAWAY and self.table_id is not None:
            raise ValueError("takeaway orders can't have a table")
        return self


class TableRef(CamelModel):
    id: int
    number: str


class PersonRef(CamelModel):
    id: int
    full_name: str


class OrderItemOut(CamelModel):
    id: int
    food_id: int
    food_name: str
    unit_price: Money
    unit_discount: Money
    final_unit_price: Money
    quantity: int
    line_total: Money
    notes: str | None


class OrderOut(CamelModel):
    id: int
    order_number: str
    order_type: OrderType
    source: OrderSource
    status: OrderStatus
    next_statuses: list[OrderStatus]
    table: TableRef | None
    waiter: PersonRef | None
    created_by: PersonRef | None
    customer_name: str | None
    customer_phone: str | None
    notes: str | None
    items: list[OrderItemOut]
    item_count: int
    subtotal: Money
    discount_total: Money
    total: Money
    cancel_reason: str | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class StatusEventOut(CamelModel):
    from_status: OrderStatus | None
    to_status: OrderStatus
    changed_by: PersonRef | None
    note: str | None
    created_at: datetime


class OrderDetailOut(OrderOut):
    history: list[StatusEventOut]


class StatusChange(CamelModel):
    status: OrderStatus
    note: str | None = Field(None, max_length=255, description="Required when cancelling")


class OrderListParams(ListParams):
    status: list[OrderStatus] | None = None
    active: bool | None = Field(None, description="Only orders that aren't paid or cancelled")
    order_type: OrderType | None = None
    table_id: int | None = None
    waiter_id: int | None = None
    date_from: date | None = Field(None, description="Restaurant local date, inclusive")
    date_to: date | None = Field(None, description="Restaurant local date, inclusive")
