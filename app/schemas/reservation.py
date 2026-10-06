from datetime import date, datetime
from typing import Annotated

from pydantic import AwareDatetime, EmailStr, Field

from app.models.reservation import ReservationSource, ReservationStatus
from app.schemas.common import CamelModel, ListParams
from app.schemas.order import PersonRef, TableRef
from app.schemas.user import Phone

PartySize = Annotated[int, Field(ge=1, le=50)]
Minutes = Annotated[int, Field(ge=15, le=480)]
CustomerName = Annotated[str, Field(min_length=1, max_length=100)]


class ReservationCreate(CamelModel):
    starts_at: AwareDatetime = Field(description="With the offset, e.g. 2026-10-10T19:30:00+06:00")
    minutes: Minutes | None = Field(None, description="Defaults to the restaurant's booking length")
    party_size: PartySize
    table_id: int | None = Field(None, description="Leave out to get the smallest free table")
    customer_name: CustomerName
    customer_phone: Phone
    customer_email: EmailStr | None = None
    notes: str | None = Field(None, max_length=500, description="e.g. birthday, high chair")


class ReservationOut(CamelModel):
    id: int
    tracking_code: str
    source: ReservationSource
    status: ReservationStatus
    next_statuses: list[ReservationStatus]
    table: TableRef | None
    party_size: int
    starts_at: datetime
    ends_at: datetime
    minutes: int
    customer_name: str
    customer_phone: str
    customer_email: str | None
    notes: str | None
    cancel_reason: str | None
    created_by: PersonRef | None
    created_at: datetime
    updated_at: datetime


class ReservationListParams(ListParams):
    status: list[ReservationStatus] | None = None
    source: ReservationSource | None = None
    table_id: int | None = None
    date_from: date | None = Field(None, description="Restaurant local date, inclusive")
    date_to: date | None = Field(None, description="Restaurant local date, inclusive")


class AvailabilityParams(CamelModel):
    starts_at: AwareDatetime
    party_size: PartySize
    minutes: Minutes | None = None
    reservation_id: int | None = Field(
        None, description="When moving a booking, so it doesn't block itself"
    )


class FreeTable(CamelModel):
    id: int
    number: str
    seats: int
    location: str | None
    is_occupied: bool = Field(description="Has an open order right now")


class Availability(CamelModel):
    starts_at: datetime
    ends_at: datetime
    party_size: int
    tables: list[FreeTable] = Field(description="Smallest tables first")
