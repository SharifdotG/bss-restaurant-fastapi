from datetime import datetime
from typing import Annotated

from pydantic import Field

from app.schemas.common import CamelModel, ListParams, WithImage

TableNumber = Annotated[str, Field(min_length=1, max_length=20)]
Seats = Annotated[int, Field(ge=1, le=50)]


class TableCreate(CamelModel):
    number: TableNumber
    seats: Seats
    location: str | None = Field(None, max_length=100)
    image_key: str | None = None
    is_active: bool = True


class TableUpdate(CamelModel):
    number: TableNumber | None = None
    seats: Seats | None = None
    location: str | None = Field(None, max_length=100)
    image_key: str | None = None
    is_active: bool | None = None


class TableEmployee(WithImage):
    id: int
    full_name: str
    designation: str


class TableOut(WithImage):
    id: int
    number: str
    seats: int
    location: str | None
    is_active: bool
    is_occupied: bool
    qr_token: str
    employees: list[TableEmployee]
    created_at: datetime
    updated_at: datetime


class TableRef(CamelModel):
    id: int
    number: str


class TableListParams(ListParams):
    is_active: bool | None = None
    min_seats: int | None = Field(None, ge=1)
    employee_id: int | None = None


class TableEmployeesIn(CamelModel):
    employee_ids: list[int] = Field(max_length=30)
