from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError, PermissionDeniedError
from app.core.pagination import apply_sort, paginate, search_filter
from app.core.timeutils import range_bounds, utcnow
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
    Payment,
    User,
    UserRole,
)
from app.models.menu import CENT
from app.models.order import NEXT_STATUSES
from app.schemas.common import Page
from app.schemas.order import (
    OrderCreate,
    OrderItemIn,
    OrderListParams,
    OrderOut,
    OrderUpdate,
    StatusChange,
)
from app.services.order_numbers import next_order_number
from app.services.restaurant import get_restaurant

# who may move an order into each status (admins always can)
STATUS_ROLES: dict[OrderStatus, set[UserRole]] = {
    OrderStatus.CONFIRMED: {UserRole.MANAGER, UserRole.WAITER, UserRole.CASHIER},
    OrderStatus.PREPARING: {UserRole.MANAGER, UserRole.CHEF},
    OrderStatus.READY: {UserRole.MANAGER, UserRole.CHEF},
    OrderStatus.SERVED: {UserRole.MANAGER, UserRole.WAITER},
    OrderStatus.CANCELLED: {UserRole.MANAGER, UserRole.WAITER, UserRole.CASHIER},
}

# the kitchen hasn't started yet, the whole item list can still be swapped
ITEMS_EDITABLE = (OrderStatus.PENDING, OrderStatus.CONFIRMED)
# new items can still be added while cooking, e.g. a dessert later on
ITEMS_APPENDABLE = (OrderStatus.PENDING, OrderStatus.CONFIRMED, OrderStatus.PREPARING)

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
        _orders()
        .options(
            selectinload(Order.history).selectinload(OrderStatusEvent.changed_by),
            selectinload(Order.payments).selectinload(Payment.received_by),
        )
        .where(Order.id == order_id)
        .execution_options(populate_existing=True)
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


def _percent_of(amount: Decimal, rate: Decimal) -> Decimal:
    return (amount * rate / 100).quantize(CENT, rounding=ROUND_HALF_UP)


def _recalculate(order: Order) -> None:
    order.subtotal = sum((i.unit_price * i.quantity for i in order.items), Decimal(0))
    order.discount_total = sum((i.unit_discount * i.quantity for i in order.items), Decimal(0))
    food_total = sum((i.line_total for i in order.items), Decimal(0))
    order.service_charge = _percent_of(food_total, order.service_charge_rate)
    # vat is charged on the service charge as well
    order.vat = _percent_of(food_total + order.service_charge, order.vat_rate)
    order.total = food_total + order.service_charge + order.vat


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
    restaurant = await get_restaurant(session)
    # service charge is for table service, takeaway doesn't pay it
    dine_in = data.order_type == OrderType.DINE_IN

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
        service_charge_rate=restaurant.service_charge_percent if dine_in else Decimal(0),
        vat_rate=restaurant.vat_percent,
    )
    order.items = _build_items(data.items, foods)
    order.history = [OrderStatusEvent(to_status=OrderStatus.PENDING, changed_by_id=actor.id)]
    _recalculate(order)

    session.add(order)
    await session.commit()
    return await get_order(session, order.id)


def close_as_paid(session: AsyncSession, order: Order, actor: User, note: str) -> None:
    session.add(
        OrderStatusEvent(
            order_id=order.id,
            from_status=order.status,
            to_status=OrderStatus.PAID,
            changed_by_id=actor.id,
            note=note,
        )
    )
    order.status = OrderStatus.PAID
    order.closed_at = utcnow()


async def change_status(
    session: AsyncSession, actor: User, order_id: int, data: StatusChange
) -> Order:
    # lock the row so two people can't move the same order at once
    order = await session.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if order is None:
        raise NotFoundError("Order not found")

    current, target = order.status, data.status
    if target not in NEXT_STATUSES[current]:
        raise ConflictError(
            f"An order can't go from {current} to {target}",
            code="invalid_status_change",
            extra={"allowed": list(NEXT_STATUSES[current])},
        )
    if target == OrderStatus.PAID:
        raise ConflictError(
            "Orders are marked paid once the bill is settled, record a payment instead",
            code="payment_required",
            extra={"balanceDue": float(order.balance_due)},
        )

    allowed_roles = STATUS_ROLES[target]
    # once the kitchen started cooking only a manager can call it off
    if target == OrderStatus.CANCELLED and current == OrderStatus.PREPARING:
        allowed_roles = {UserRole.MANAGER}
    if actor.role != UserRole.ADMIN and actor.role not in allowed_roles:
        raise PermissionDeniedError(f"Your role can't mark orders as {target}")

    note = data.note.strip() if data.note else None
    if target == OrderStatus.CANCELLED:
        if not note:
            raise BadRequestError("Give a reason for cancelling", code="reason_required")
        order.cancel_reason = note

    order.status = target
    if order.is_closed:
        order.closed_at = utcnow()
    session.add(
        OrderStatusEvent(
            order_id=order.id,
            from_status=current,
            to_status=target,
            changed_by_id=actor.id,
            note=note,
        )
    )
    # paid up front, e.g. takeaway paid at the counter, so it's done once handed over
    if target == OrderStatus.SERVED and order.amount_paid >= order.total:
        close_as_paid(session, order, actor, "paid before serving")
    await session.commit()
    return await get_order(session, order.id)


async def _lock_order(session: AsyncSession, order_id: int) -> Order:
    order = await session.scalar(
        select(Order)
        .options(selectinload(Order.items))
        .where(Order.id == order_id)
        .with_for_update()
    )
    if order is None:
        raise NotFoundError("Order not found")
    if order.is_closed:
        raise ConflictError(f"The order is already {order.status}", code="order_closed")
    return order


async def update_order(
    session: AsyncSession, actor: User, order_id: int, data: OrderUpdate
) -> Order:
    order = await _lock_order(session, order_id)
    changes = data.model_dump(exclude_unset=True)

    if "table_id" in changes:
        if order.order_type != OrderType.DINE_IN:
            raise BadRequestError("Takeaway orders don't have a table", code="invalid_table")
        if changes["table_id"] is None:
            raise BadRequestError("Dine in orders need a table", code="invalid_table")
        await _check_table(session, changes["table_id"])
    if changes.get("waiter_id") is not None:
        changes["waiter_id"] = await _resolve_waiter(session, actor, changes["waiter_id"])

    for field, value in changes.items():
        setattr(order, field, value)
    await session.commit()
    return await get_order(session, order.id)


async def replace_items(
    session: AsyncSession, order_id: int, items: Sequence[OrderItemIn]
) -> Order:
    order = await _lock_order(session, order_id)
    if order.status not in ITEMS_EDITABLE:
        raise ConflictError(
            "The kitchen already started on this order, add new items instead",
            code="order_locked",
        )

    foods = await _load_foods(session, items)
    order.items = _build_items(items, foods)
    _recalculate(order)
    await session.commit()
    return await get_order(session, order.id)


async def add_items(session: AsyncSession, order_id: int, items: Sequence[OrderItemIn]) -> Order:
    order = await _lock_order(session, order_id)
    if order.status not in ITEMS_APPENDABLE:
        raise ConflictError("Items can't be added to this order anymore", code="order_locked")

    foods = await _load_foods(session, items)
    # added as separate lines so the original lines keep their price snapshot
    order.items.extend(_build_items(items, foods))
    _recalculate(order)
    await session.commit()
    return await get_order(session, order.id)
