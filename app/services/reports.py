from datetime import datetime

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Category, Food, Order, OrderItem, OrderStatus
from app.schemas.report import TopFood, TopFoodParams, TopFoodsReport


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
