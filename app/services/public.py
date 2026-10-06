from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.timeutils import business_date, is_open_between, opening_window, utcnow
from app.models import (
    HOLDS_TABLE,
    Category,
    DiningTable,
    Food,
    Order,
    OrderSource,
    OrderStatus,
    OrderStatusEvent,
    OrderType,
    Reservation,
    ReservationSource,
    ReservationStatus,
    Restaurant,
)
from app.schemas.public import (
    Menu,
    MenuCategory,
    MenuFood,
    OnlineOrderCreate,
    PublicOrderCreate,
    PublicReservationCreate,
    PublicRestaurant,
    Slot,
    Slots,
)
from app.services.orders import build_order, get_order
from app.services.reservations import free_tables, get_reservation, save_booking
from app.services.restaurant import get_restaurant

# orders from one table nobody has confirmed yet, stops a prank from flooding the kitchen
MAX_WAITING_QR_ORDERS = 3
# same idea for website orders, per phone number
MAX_WAITING_ONLINE_ORDERS = 3
CUSTOMER_CANCELLED = "Cancelled by the customer"

# website bookings start on the half hour from opening time
SLOT_MINUTES = 30
# the kitchen likes to know a bit ahead, later than that people should call
MIN_NOTICE = timedelta(hours=1)
MAX_DAYS_AHEAD = 60
# upcoming bookings per phone number, so nobody books every table for fun
MAX_UPCOMING_BOOKINGS = 3
CUSTOMER_CAN_CANCEL = (ReservationStatus.REQUESTED, ReservationStatus.CONFIRMED)


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


async def _accepting_bookings(session: AsyncSession) -> Restaurant:
    restaurant = await get_restaurant(session)
    if not restaurant.accepts_reservations:
        raise ConflictError(
            "Online booking is switched off, please call us", code="reservations_disabled"
        )
    return restaurant


async def available_slots(session: AsyncSession, day: date, party_size: int) -> Slots:
    """Start times on a day with at least one table free for the party."""
    restaurant = await _accepting_bookings(session)
    length = timedelta(minutes=restaurant.reservation_minutes)
    open_at, close_at = opening_window(day, restaurant.opens_at, restaurant.closes_at)
    earliest = utcnow() + MIN_NOTICE
    result = Slots(day=day, party_size=party_size, minutes=restaurant.reservation_minutes, slots=[])
    if day < business_date() or day > business_date() + timedelta(days=MAX_DAYS_AHEAD):
        return result

    tables = list(
        await session.scalars(
            select(DiningTable.id).where(
                DiningTable.is_active.is_(True), DiningTable.seats >= party_size
            )
        )
    )
    booked: dict[int, list[tuple[datetime, datetime]]] = defaultdict(list)
    rows = await session.execute(
        select(Reservation.table_id, Reservation.starts_at, Reservation.ends_at).where(
            Reservation.table_id.in_(tables),
            Reservation.status.in_(HOLDS_TABLE),
            Reservation.starts_at < close_at,
            Reservation.ends_at > open_at,
        )
    )
    for table_id, starts_at, ends_at in rows:
        booked[table_id].append((starts_at, ends_at))

    def is_free(table_id: int, start: datetime, end: datetime) -> bool:
        return all(not (s < end and e > start) for s, e in booked[table_id])

    start = open_at
    while start + length <= close_at:
        end = start + length
        if start >= earliest and any(is_free(t, start, end) for t in tables):
            result.slots.append(Slot(starts_at=start, ends_at=end))
        start += timedelta(minutes=SLOT_MINUTES)
    return result


async def request_reservation(session: AsyncSession, data: PublicReservationCreate) -> Reservation:
    """A booking from the website. Staff confirm it, unless the restaurant lets free
    tables be given out straight away."""
    restaurant = await _accepting_bookings(session)
    starts_at = data.starts_at
    ends_at = starts_at + timedelta(minutes=restaurant.reservation_minutes)
    now = utcnow()
    if starts_at < now + MIN_NOTICE:
        raise BadRequestError(
            "That's too soon to book online, please call us", code="too_short_notice"
        )
    if starts_at > now + timedelta(days=MAX_DAYS_AHEAD):
        raise BadRequestError(f"Bookings open {MAX_DAYS_AHEAD} days ahead", code="too_far_ahead")
    if not is_open_between(starts_at, ends_at, restaurant.opens_at, restaurant.closes_at):
        raise BadRequestError(
            "We're closed at that time",
            code="outside_opening_hours",
            extra={
                "opensAt": restaurant.opens_at.isoformat(),
                "closesAt": restaurant.closes_at.isoformat(),
            },
        )

    upcoming = await session.scalar(
        select(func.count()).where(
            Reservation.customer_phone == data.customer_phone,
            Reservation.status.in_(CUSTOMER_CAN_CANCEL),
            Reservation.ends_at > now,
        )
    )
    if upcoming >= MAX_UPCOMING_BOOKINGS:
        raise ConflictError(
            "You already have bookings coming up, please call us for more",
            code="too_many_bookings",
        )

    tables = await free_tables(session, starts_at, ends_at, data.party_size)
    if not tables:
        raise ConflictError(
            f"No table for {data.party_size} is free then, please try another time",
            code="no_table_available",
        )

    reservation = Reservation(
        source=ReservationSource.ONLINE,
        status=ReservationStatus.REQUESTED,
        ends_at=ends_at,
        **data.model_dump(),
    )
    if restaurant.auto_confirm_reservations:
        reservation.status = ReservationStatus.CONFIRMED
        reservation.table_id = tables[0].id
    session.add(reservation)
    await save_booking(session)
    return await get_reservation(session, reservation.id)


async def get_public_reservation(session: AsyncSession, tracking_code: str) -> Reservation:
    reservation_id = await session.scalar(
        select(Reservation.id).where(Reservation.tracking_code == tracking_code)
    )
    if reservation_id is None:
        raise NotFoundError("Booking not found")
    return await get_reservation(session, reservation_id)


async def cancel_public_reservation(session: AsyncSession, tracking_code: str) -> Reservation:
    reservation = await session.scalar(
        select(Reservation).where(Reservation.tracking_code == tracking_code).with_for_update()
    )
    if reservation is None:
        raise NotFoundError("Booking not found")
    if reservation.status not in CUSTOMER_CAN_CANCEL or reservation.starts_at <= utcnow():
        raise ConflictError(
            "This booking can't be cancelled anymore, please call us", code="cancel_not_allowed"
        )

    reservation.status = ReservationStatus.CANCELLED
    reservation.cancel_reason = CUSTOMER_CANCELLED
    await session.commit()
    return await get_reservation(session, reservation.id)
