from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Date, DateTime, cast, distinct, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Category, Expense, Food, Order, OrderItem, OrderStatus
from app.models.menu import CENT
from app.schemas.report import (
    GroupBy,
    PeriodSummary,
    SalesParams,
    SalesReport,
    SalesRow,
    SalesSummary,
    TopFood,
    TopFoodParams,
    TopFoodsReport,
)


def summarize(orders: int, sales: Decimal | None, expenses: Decimal | None) -> PeriodSummary:
    sales = sales or Decimal(0)
    expenses = expenses or Decimal(0)
    average = (sales / orders).quantize(CENT) if orders else Decimal(0)
    return PeriodSummary(
        orders=orders,
        sales=sales,
        expenses=expenses,
        profit=sales - expenses,
        average_order=average,
    )


def period_floor(day: date, group_by: GroupBy) -> date:
    """Same as postgres date_trunc, weeks start on monday there too."""
    match group_by:
        case GroupBy.DAY:
            return day
        case GroupBy.WEEK:
            return day - timedelta(days=day.weekday())
        case GroupBy.MONTH:
            return day.replace(day=1)
        case GroupBy.YEAR:
            return day.replace(month=1, day=1)


def next_period(start: date, group_by: GroupBy) -> date:
    match group_by:
        case GroupBy.DAY:
            return start + timedelta(days=1)
        case GroupBy.WEEK:
            return start + timedelta(days=7)
        case GroupBy.MONTH:
            return (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        case GroupBy.YEAR:
            return start.replace(year=start.year + 1)


def periods(start: date, end: date, group_by: GroupBy) -> list[date]:
    found = []
    current = period_floor(start, group_by)
    while current <= end:
        found.append(current)
        current = next_period(current, group_by)
    return found


def _bucket(group_by: GroupBy, column):
    # rendered inline: postgres only matches the GROUP BY to the select list when
    # both are the exact same expression, two separate bind params aren't
    unit = literal(group_by.value, literal_execute=True)
    return cast(func.date_trunc(unit, column), Date).label("period")


async def sales_report(session: AsyncSession, params: SalesParams) -> SalesReport:
    start, end = params.bounds
    tz = literal(settings.restaurant_tz, literal_execute=True)
    # paid orders count on the local day they were paid
    order_bucket = _bucket(params.group_by, func.timezone(tz, Order.closed_at))
    sales_rows = await session.execute(
        select(
            order_bucket,
            func.count().label("orders"),
            func.sum(Order.total).label("sales"),
            func.sum(Order.discount_total).label("discounts"),
        )
        .where(
            Order.status == OrderStatus.PAID,
            Order.closed_at >= start,
            Order.closed_at < end,
        )
        .group_by(order_bucket)
    )
    sales = {row.period: row for row in sales_rows}

    expense_bucket = _bucket(params.group_by, cast(Expense.expense_date, DateTime))
    expense_rows = await session.execute(
        select(expense_bucket, func.sum(Expense.amount).label("amount"))
        .where(Expense.expense_date.between(params.start, params.end))
        .group_by(expense_bucket)
    )
    expenses = {row.period: row.amount for row in expense_rows}

    # periods without any sale still get a row, charts need the gaps
    rows = []
    for period in periods(params.start, params.end, params.group_by):
        last_day = next_period(period, params.group_by) - timedelta(days=1)
        sold = sales.get(period)
        summary = (
            summarize(sold.orders, sold.sales, expenses.get(period))
            if sold
            else summarize(0, None, expenses.get(period))
        )
        rows.append(
            SalesRow(
                **summary.model_dump(),
                discounts=sold.discounts if sold else Decimal(0),
                period_start=max(period, params.start),
                period_end=min(last_day, params.end),
            )
        )

    totals = summarize(
        sum(row.orders for row in rows),
        sum((row.sales for row in rows), Decimal(0)),
        sum((row.expenses for row in rows), Decimal(0)),
    )
    return SalesReport(
        date_from=params.start,
        date_to=params.end,
        group_by=params.group_by,
        totals=SalesSummary(
            **totals.model_dump(), discounts=sum((row.discounts for row in rows), Decimal(0))
        ),
        rows=rows,
    )


async def top_foods(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    limit: int = 10,
    category_id: int | None = None,
) -> list[TopFood]:
    """Best sellers between two moments, only counting orders that were paid."""
    quantity = func.sum(OrderItem.quantity)
    stmt = (
        select(
            Food.id,
            Food.name,
            Food.image_key,
            Category.name.label("category"),
            quantity.label("quantity"),
            func.count(distinct(OrderItem.order_id)).label("orders"),
            func.sum(OrderItem.line_total).label("revenue"),
        )
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .join(Food, Food.id == OrderItem.food_id)
        .outerjoin(Category, Category.id == Food.category_id)
        .where(
            Order.status == OrderStatus.PAID,
            Order.closed_at >= start,
            Order.closed_at < end,
        )
        .group_by(Food.id, Category.name)
        .order_by(quantity.desc(), Food.id)
        .limit(limit)
    )
    if category_id is not None:
        stmt = stmt.where(Food.category_id == category_id)

    rows = await session.execute(stmt)
    return [TopFood.model_validate(row) for row in rows.mappings()]


async def top_foods_report(session: AsyncSession, params: TopFoodParams) -> TopFoodsReport:
    start, end = params.bounds
    items = await top_foods(session, start, end, params.limit, params.category_id)
    return TopFoodsReport(date_from=params.start, date_to=params.end, items=items)
