from datetime import date, datetime
from typing import Self

from pydantic import Field, model_validator

from app.core.timeutils import business_date, range_bounds
from app.schemas.common import CamelModel, Money, WithImage

MAX_RANGE_DAYS = 3660


class ReportRange(CamelModel):
    """Both days are included. Defaults to the current month so far."""

    date_from: date | None = None
    date_to: date | None = None

    @model_validator(mode="after")
    def _fill_defaults(self) -> Self:
        self.date_to = self.date_to or business_date()
        self.date_from = self.date_from or self.date_to.replace(day=1)
        if self.date_from > self.date_to:
            raise ValueError("dateFrom must be on or before dateTo")
        if (self.date_to - self.date_from).days > MAX_RANGE_DAYS:
            raise ValueError("range can't be longer than 10 years")
        return self

    @property
    def start(self) -> date:
        assert self.date_from is not None
        return self.date_from

    @property
    def end(self) -> date:
        assert self.date_to is not None
        return self.date_to

    @property
    def bounds(self) -> tuple[datetime, datetime]:
        return range_bounds(self.start, self.end)


class TopFoodParams(ReportRange):
    limit: int = Field(10, ge=1, le=50)
    category_id: int | None = None


class TopFood(WithImage):
    id: int
    name: str
    category: str | None
    quantity: int
    orders: int
    revenue: Money


class TopFoodsReport(CamelModel):
    date_from: date
    date_to: date
    items: list[TopFood]
