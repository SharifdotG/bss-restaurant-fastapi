from datetime import datetime

from app.models.order import OrderSource, OrderStatus, OrderType
from app.models.reservation import ReservationSource, ReservationStatus
from app.schemas.common import CamelModel, Money
from app.schemas.order import PersonRef, TableRef

# kept small on purpose, an event has to fit in a postgres NOTIFY (8000 bytes)


class LiveItem(CamelModel):
    food_name: str
    quantity: int
    notes: str | None


class LiveOrder(CamelModel):
    id: int
    order_number: str
    order_type: OrderType
    source: OrderSource
    status: OrderStatus
    table: TableRef | None
    waiter: PersonRef | None
    customer_name: str | None
    notes: str | None
    items: list[LiveItem]
    item_count: int
    total: Money
    balance_due: Money
    created_at: datetime
    updated_at: datetime


class LiveReservation(CamelModel):
    id: int
    source: ReservationSource
    status: ReservationStatus
    table: TableRef | None
    party_size: int
    starts_at: datetime
    ends_at: datetime
    customer_name: str
    customer_phone: str
    notes: str | None
    updated_at: datetime
