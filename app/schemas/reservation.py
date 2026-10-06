from datetime import date, datetime
from typing import Annotated, Self

from pydantic import AwareDatetime, EmailStr, Field, model_validator

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


class ReservationUpdate(CamelModel):
    """Only while the booking is requested or confirmed, the table is checked again."""

    starts_at: AwareDatetime | None = None
    minutes: Minutes | None = None
    party_size: PartySize | None = None
    table_id: int | None = None
    customer_name: CustomerName | None = None
    customer_phone: Phone | None = None
    customer_email: EmailStr | None = None
    notes: str | None = Field(None, max_length=500)


class ReservationStatusChange(CamelModel):
    status: ReservationStatus
    table_id: int | None = Field(
        None, description="When confirming, leave out to keep the table or get a free one"
    )
    note: str | None = Field(None, max_length=255, description="Required to cancel or decline")

    @model_validator(mode="after")
    def _table_only_when_confirming(self) -> Self:
        if self.table_id is not None and self.status != ReservationStatus.CONFIRMED:
            raise ValueError("a table can only be given when confirming")
        return self


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
