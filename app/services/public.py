from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.timeutils import utcnow
from app.models import (
    Category,
    DiningTable,
    Food,
    Order,
    OrderSource,
    OrderStatus,
    OrderStatusEvent,
    OrderType,
)
from app.schemas.public import (
    Menu,
    MenuCategory,
    MenuFood,
    OnlineOrderCreate,
    PublicOrderCreate,
    PublicRestaurant,
)
from app.services.orders import build_order, get_order
from app.services.restaurant import get_restaurant

# orders from one table nobody has confirmed yet, stops a prank from flooding the kitchen
MAX_WAITING_QR_ORDERS = 3
# same idea for website orders, per phone number
MAX_WAITING_ONLINE_ORDERS = 3
CUSTOMER_CANCELLED = "Cancelled by the customer"


async def get_menu(session: AsyncSession) -> Menu:
    """The whole menu in one go, grouped by category. Sold out foods stay in so the
    frontend can show them greyed out, hidden categories and deleted foods don't."""
    restaurant = await get_restaurant(session)
    categories = await session.scalars(
        select(Category)
        .where(Category.is_active.is_(True))
        .order_by(Category.sort_order, Category.name)
    )
    foods = await session.scalars(
        select(Food).where(Food.deleted_at.is_(None)).order_by(Food.is_featured.desc(), Food.name)
    )

    by_category: dict[int | None, list[MenuFood]] = defaultdict(list)
    for food in foods:
        by_category[food.category_id].append(MenuFood.model_validate(food))

    return Menu(
        restaurant=PublicRestaurant.model_validate(restaurant),
        categories=[
            MenuCategory(
                id=category.id,
                name=category.name,
                description=category.description,
                image_key=category.image_key,
                foods=by_category[category.id],
            )
            for category in categories
            if by_category[category.id]
        ],
        uncategorized=by_category[None],
    )


async def get_table(session: AsyncSession, qr_token: str, lock: bool = False) -> DiningTable:
    stmt = select(DiningTable).where(
        DiningTable.qr_token == qr_token, DiningTable.is_active.is_(True)
    )
    if lock:
        stmt = stmt.with_for_update()
    table = await session.scalar(stmt)
    if table is None:
        raise NotFoundError("This QR code doesn't work anymore, please ask a waiter")
    return table


async def get_public_order(session: AsyncSession, tracking_code: str) -> Order:
    order_id = await session.scalar(select(Order.id).where(Order.tracking_code == tracking_code))
    if order_id is None:
        raise NotFoundError("Order not found")
    return await get_order(session, order_id)


async def place_table_order(session: AsyncSession, qr_token: str, data: PublicOrderCreate) -> Order:
    """A customer ordering from the QR code on their table. Staff still confirm it."""
    restaurant = await get_restaurant(session)
    if not restaurant.accepts_qr_orders:
        raise ConflictError(
            "Ordering from the table is switched off, please ask a waiter",
            code="qr_orders_disabled",
        )
    # locked so two phones at the same table can't both slip past the limit
    table = await get_table(session, qr_token, lock=True)
    waiting = await session.scalar(
        select(func.count()).where(
            Order.table_id == table.id,
            Order.source == OrderSource.QR,
            Order.status == OrderStatus.PENDING,
        )
    )
    if waiting >= MAX_WAITING_QR_ORDERS:
        raise ConflictError(
            "This table already has orders waiting, a waiter will be with you shortly",
            code="too_many_waiting_orders",
        )

    order = await build_order(
        session,
        order_type=OrderType.DINE_IN,
        source=OrderSource.QR,
        table_id=table.id,
        items=data.items,
        customer_name=data.customer_name,
        customer_phone=data.customer_phone,
        notes=data.notes,
    )
    await session.commit()
    return await get_order(session, order.id)


async def place_online_order(session: AsyncSession, data: OnlineOrderCreate) -> Order:
    """Takeaway ordered on the website, staff confirm it and call if something is off."""
    restaurant = await get_restaurant(session)
    if not restaurant.accepts_online_orders:
        raise ConflictError(
            "Online orders are switched off at the moment", code="online_orders_disabled"
        )
    waiting = await session.scalar(
        select(func.count()).where(
            Order.customer_phone == data.customer_phone,
            Order.source == OrderSource.ONLINE,
            Order.status == OrderStatus.PENDING,
        )
    )
    if waiting >= MAX_WAITING_ONLINE_ORDERS:
        raise ConflictError(
            "You already have orders waiting, the restaurant will call you shortly",
            code="too_many_waiting_orders",
        )

    order = await build_order(
        session,
        order_type=OrderType.TAKEAWAY,
        source=OrderSource.ONLINE,
        items=data.items,
        customer_name=data.customer_name,
        customer_phone=data.customer_phone,
        notes=data.notes,
    )
    await session.commit()
    return await get_order(session, order.id)


async def cancel_public_order(session: AsyncSession, tracking_code: str) -> Order:
    """Customers can take an order back until the restaurant accepts it."""
    order = await session.scalar(
        select(Order).where(Order.tracking_code == tracking_code).with_for_update()
    )
    if order is None:
        raise NotFoundError("Order not found")
    if (
        order.source == OrderSource.STAFF
        or order.status != OrderStatus.PENDING
        or order.amount_paid > 0
    ):
        raise ConflictError(
            "The restaurant is already working on this order, please ask the staff to cancel it",
            code="cancel_not_allowed",
        )

    session.add(
        OrderStatusEvent(
            order_id=order.id,
            from_status=order.status,
            to_status=OrderStatus.CANCELLED,
            note=CUSTOMER_CANCELLED,
        )
    )
    order.status = OrderStatus.CANCELLED
    order.cancel_reason = CUSTOMER_CANCELLED
    order.closed_at = utcnow()
    await session.commit()
    return await get_order(session, order.id)
