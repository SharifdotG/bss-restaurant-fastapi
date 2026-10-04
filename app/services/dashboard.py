from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.timeutils import business_date, day_bounds
from app.models import (
    ACTIVE_STATUSES,
    DiningTable,
    Employee,
    Expense,
    Food,
    Order,
    OrderStatus,
    Payment,
)
from app.schemas.report import (
    Dashboard,
    MenuStats,
    OpenOrders,
    RecentOrder,
    TableStats,
)
from app.services.reports import refunds_after_sale, summarize, top_foods

PERIODS = ("today", "this_month", "this_year", "all_time")


def _count(*criteria):
    return select(func.count()).where(*criteria).scalar_subquery()


async def get_dashboard(session: AsyncSession) -> Dashboard:
    # the old dashboard ran ~20 queries one after another, this does the same in six
    today = business_date()
    period_start = {
        "today": today,
        "this_month": today.replace(day=1),
        "this_year": today.replace(month=1, day=1),
    }
    today_start, today_end = day_bounds(today)
    paid = Order.status == OrderStatus.PAID

    order_columns = []
    for name in PERIODS:
        criteria = [paid]
        if name in period_start:
            criteria.append(Order.closed_at >= day_bounds(period_start[name])[0])
        order_columns += [
            func.count().filter(*criteria).label(f"{name}_orders"),
            func.sum(Order.total).filter(*criteria).label(f"{name}_sales"),
            func.sum(Order.vat).filter(*criteria).label(f"{name}_vat"),
        ]
    order_columns += [
        func.count()
        .filter(Order.created_at >= today_start, Order.status != OrderStatus.CANCELLED)
        .label("orders_today"),
        func.count()
        .filter(Order.status == OrderStatus.CANCELLED, Order.closed_at >= today_start)
        .label("cancelled_today"),
        *(func.count().filter(Order.status == status).label(status) for status in ACTIVE_STATUSES),
    ]
    orders = (await session.execute(select(*order_columns).select_from(Order))).one()._mapping

    expense_columns = [
        func.sum(Expense.amount).filter(Expense.expense_date >= day).label(name)
        for name, day in period_start.items()
    ]
    expense_columns.append(func.sum(Expense.amount).label("all_time"))
    expenses = (await session.execute(select(*expense_columns))).one()._mapping

    refund_columns = [
        func.sum(Payment.amount).filter(Payment.created_at >= day_bounds(day)[0]).label(name)
        for name, day in period_start.items()
    ]
    refund_columns.append(func.sum(Payment.amount).label("all_time"))
    refunds = (await session.execute(refunds_after_sale(*refund_columns))).one()._mapping

    counts = (
        await session.execute(
            select(
                _count(DiningTable.is_active).label("tables"),
                _count(DiningTable.is_active, DiningTable.is_occupied).label("occupied"),
                _count(Employee.is_active).label("employees"),
                _count(Food.deleted_at.is_(None)).label("foods"),
                _count(Food.deleted_at.is_(None), Food.is_available).label("available"),
            )
        )
    ).one()

    recent = await session.scalars(
        select(Order)
        .options(joinedload(Order.table))
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(5)
    )
    month_start = day_bounds(period_start["this_month"])[0]
    best_sellers = await top_foods(session, month_start, today_end, limit=5)

    open_orders = {status.value: orders[status] for status in ACTIVE_STATUSES}
    return Dashboard(
        business_date=today,
        **{
            name: summarize(
                orders[f"{name}_orders"],
                orders[f"{name}_sales"],
                expenses[name],
                orders[f"{name}_vat"],
                refunds[name],
            )
            for name in PERIODS
        },
        orders_today=orders["orders_today"],
        cancelled_today=orders["cancelled_today"],
        open_orders=OpenOrders(**open_orders, total=sum(open_orders.values())),
        tables=TableStats(
            total=counts.tables, occupied=counts.occupied, free=counts.tables - counts.occupied
        ),
        active_employees=counts.employees,
        menu=MenuStats(foods=counts.foods, available=counts.available),
        recent_orders=[RecentOrder.model_validate(order) for order in recent],
        top_foods_this_month=best_sellers,
    )
