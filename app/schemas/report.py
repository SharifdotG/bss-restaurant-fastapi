from datetime import date, datetime
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from app.core.timeutils import business_date, range_bounds
from app.models.expense import ExpenseCategory
from app.models.order import OrderStatus, OrderType
from app.schemas.common import CamelModel, Money, WithImage
from app.schemas.order import PersonRef, TableRef

MAX_RANGE_DAYS = 3660
MAX_DAILY_POINTS = 400


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


class GroupBy(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


class SalesParams(ReportRange):
    group_by: GroupBy = GroupBy.DAY

    @model_validator(mode="after")
    def _limit_points(self) -> Self:
        if self.group_by == GroupBy.DAY and (self.end - self.start).days >= MAX_DAILY_POINTS:
            raise ValueError("too many days for groupBy=day, use week or month")
        return self


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


class ExpenseShare(CamelModel):
    category: ExpenseCategory
    count: int
    amount: Money
    share: float = Field(description="Percent of all expenses in the range")


class ExpenseReport(CamelModel):
    date_from: date
    date_to: date
    total: Money
    categories: list[ExpenseShare]


class StaffMember(PersonRef):
    designation: str
    is_active: bool


class StaffRow(CamelModel):
    employee: StaffMember
    orders: int = Field(description="Paid orders where this employee was the waiter")
    items_sold: int
    sales: Money
    average_order: Money
    cancelled: int
    share: float = Field(description="Percent of the sales of everyone in the report")


class StaffReport(CamelModel):
    date_from: date
    date_to: date
    total_sales: Money
    rows: list[StaffRow]


class PeriodSummary(CamelModel):
    orders: int = Field(description="Paid orders")
    sales: Money = Field(description="What customers paid, VAT and service charge included")
    vat: Money
    refunds: Money = Field(description="Money given back after an order was paid")
    expenses: Money
    profit: Money = Field(description="Sales minus VAT, refunds and expenses")
    average_order: Money


class SalesSummary(PeriodSummary):
    discounts: Money


class SalesRow(SalesSummary):
    """One day, week, month or year. The first and last ones are cut to the requested range."""

    period_start: date
    period_end: date


class SalesReport(CamelModel):
    date_from: date
    date_to: date
    group_by: GroupBy
    totals: SalesSummary
    rows: list[SalesRow]


class OpenOrders(CamelModel):
    pending: int
    confirmed: int
    preparing: int
    ready: int
    served: int
    total: int


class TableStats(CamelModel):
    total: int
    occupied: int
    free: int


class MenuStats(CamelModel):
    foods: int
    available: int


class RecentOrder(CamelModel):
    id: int
    order_number: str
    order_type: OrderType
    status: OrderStatus
    table: TableRef | None
    total: Money
    created_at: datetime


class Dashboard(CamelModel):
    business_date: date
    today: PeriodSummary
    this_month: PeriodSummary
    this_year: PeriodSummary
    all_time: PeriodSummary
    orders_today: int = Field(description="Placed today, cancelled ones not included")
    cancelled_today: int
    open_orders: OpenOrders
    tables: TableStats
    active_employees: int
    menu: MenuStats
    recent_orders: list[RecentOrder]
    top_foods_this_month: list[TopFood]
