from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestError, NotFoundError
from app.core.pagination import apply_sort, paginate, search_filter
from app.core.timeutils import range_bounds
from app.models import (
    ACTIVE_STATUSES,
    DiningTable,
    Employee,
    Food,
    Order,
    OrderItem,
    OrderStatus,
    OrderStatusEvent,
    OrderType,
    User,
)
from app.schemas.common import Page
from app.schemas.order import OrderCreate, OrderItemIn, OrderListParams, OrderOut
from app.services.order_numbers import next_order_number

ORDER_SORTS = {
    "createdAt": Order.created_at,
    "orderNumber": Order.order_number,
    "total": Order.total,
    "status": Order.status,
}


def _orders():
    return select(Order).options(
        selectinload(Order.items),
        selectinload(Order.table),
        selectinload(Order.waiter),
        selectinload(Order.created_by),
    )


async def get_order(session: AsyncSession, order_id: int) -> Order:
    order = await session.scalar(
        _orders().where(Order.id == order_id).execution_options(populate_existing=True)
    )
    if order is None:
        raise NotFoundError("Order not found")
    return order


async def list_orders(session: AsyncSession, params: OrderListParams) -> Page[OrderOut]:
    stmt = _orders()
    if params.status:
        stmt = stmt.where(Order.status.in_(params.status))
    if params.active is not None:
        active = Order.status.in_(ACTIVE_STATUSES)
        stmt = stmt.where(active if params.active else ~active)
    if params.order_type is not None:
        stmt = stmt.where(Order.order_type == params.order_type)
    if params.table_id is not None:
        stmt = stmt.where(Order.table_id == params.table_id)
    if params.waiter_id is not None:
        stmt = stmt.where(Order.waiter_id == params.waiter_id)
    if params.date_from or params.date_to:
        start, end = range_bounds(
            params.date_from or params.date_to, params.date_to or params.date_from
        )
        stmt = stmt.where(Order.created_at >= start, Order.created_at < end)
    term = search_filter(
        params.search, Order.order_number, Order.customer_name, Order.customer_phone
    )
    if term is not None:
        stmt = stmt.where(term)

    stmt = apply_sort(stmt, params.sort, ORDER_SORTS, default="-createdAt", tiebreaker=Order.id)
    return await paginate(session, stmt, params, OrderOut)


async def _load_foods(session: AsyncSession, items: Sequence[OrderItemIn]) -> dict[int, Food]:
    ids = {item.food_id for item in items}
    foods = {
        food.id: food
        for food in await session.scalars(
            select(Food).where(Food.id.in_(ids), Food.deleted_at.is_(None))
        )
    }
    if missing := sorted(ids - foods.keys()):
        raise BadRequestError(
            "Some foods don't exist", code="unknown_foods", extra={"foodIds": missing}
        )
    if unavailable := sorted(f.id for f in foods.values() if not f.is_available):
        raise BadRequestError(
            "Some foods are not available right now",
            code="foods_unavailable",
            extra={"foodIds": unavailable},
        )
    return foods


def _build_items(items: Sequence[OrderItemIn], foods: dict[int, Food]) -> list[OrderItem]:
    # the same food with the same note is one line, just with a bigger quantity
    merged: dict[tuple[int, str | None], int] = {}
    for item in items:
        key = (item.food_id, item.notes.strip() if item.notes else None)
        merged[key] = merged.get(key, 0) + item.quantity

    lines = []
    for (food_id, notes), quantity in merged.items():
        if quantity > 100:
            raise BadRequestError("Quantity per item can be at most 100", code="quantity_too_high")
        food = foods[food_id]
        final_price = food.final_price
        lines.append(
            OrderItem(
                food_id=food.id,
                food_name=food.name,
                unit_price=food.price,
                unit_discount=food.price - final_price,
                final_unit_price=final_price,
                quantity=quantity,
                line_total=final_price * quantity,
                notes=notes,
            )
        )
    return lines


def _recalculate(order: Order) -> None:
    order.subtotal = sum((i.unit_price * i.quantity for i in order.items), Decimal(0))
    order.discount_total = sum((i.unit_discount * i.quantity for i in order.items), Decimal(0))
    order.total = sum((i.line_total for i in order.items), Decimal(0))


async def _check_table(session: AsyncSession, table_id: int) -> None:
    table = await session.get(DiningTable, table_id)
    if table is None or not table.is_active:
        raise BadRequestError("Table doesn't exist or is not in use", code="invalid_table")


async def _resolve_waiter(session: AsyncSession, actor: User, waiter_id: int | None) -> int | None:
    if waiter_id is not None:
        waiter = await session.get(Employee, waiter_id)
        if waiter is None or not waiter.is_active:
            raise BadRequestError("Waiter doesn't exist or is inactive", code="invalid_waiter")
        return waiter.id
    # whoever takes the order is the waiter, if they have an employee record
    return await session.scalar(
        select(Employee.id).where(Employee.user_id == actor.id, Employee.is_active.is_(True))
    )


async def create_order(session: AsyncSession, actor: User, data: OrderCreate) -> Order:
    if data.order_type == OrderType.DINE_IN:
        await _check_table(session, data.table_id)
    foods = await _load_foods(session, data.items)

    order = Order(
        order_number=await next_order_number(session),
        order_type=data.order_type,
        table_id=data.table_id,
        waiter_id=await _resolve_waiter(session, actor, data.waiter_id),
        created_by_id=actor.id,
        customer_name=data.customer_name,
        customer_phone=data.customer_phone,
        notes=data.notes,
        status=OrderStatus.PENDING,
    )
    order.items = _build_items(data.items, foods)
    order.history = [OrderStatusEvent(to_status=OrderStatus.PENDING, changed_by_id=actor.id)]
    _recalculate(order)

    session.add(order)
    await session.commit()
    return await get_order(session, order.id)
