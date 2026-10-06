from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.pagination import apply_sort, paginate, search_filter
from app.core.timeutils import range_bounds, utcnow
from app.models import (
    HOLDS_TABLE,
    DiningTable,
    Reservation,
    ReservationSource,
    ReservationStatus,
    User,
)
from app.schemas.common import Page
from app.schemas.reservation import (
    Availability,
    AvailabilityParams,
    FreeTable,
    ReservationCreate,
    ReservationListParams,
    ReservationOut,
)
from app.services.common import commit_or_conflict
from app.services.restaurant import get_restaurant

# a booking a few minutes in the past is fine, guests are standing at the door
PAST_GRACE = timedelta(minutes=15)

RESERVATION_SORTS = {
    "startsAt": Reservation.starts_at,
    "partySize": Reservation.party_size,
    "customerName": Reservation.customer_name,
    "createdAt": Reservation.created_at,
}


def _reservations():
    return select(Reservation).options(
        selectinload(Reservation.table), selectinload(Reservation.created_by)
    )


async def get_reservation(session: AsyncSession, reservation_id: int) -> Reservation:
    reservation = await session.scalar(
        _reservations()
        .where(Reservation.id == reservation_id)
        .execution_options(populate_existing=True)
    )
    if reservation is None:
        raise NotFoundError("Reservation not found")
    return reservation


async def list_reservations(
    session: AsyncSession, params: ReservationListParams
) -> Page[ReservationOut]:
    stmt = _reservations()
    if params.status:
        stmt = stmt.where(Reservation.status.in_(params.status))
    if params.source is not None:
        stmt = stmt.where(Reservation.source == params.source)
    if params.table_id is not None:
        stmt = stmt.where(Reservation.table_id == params.table_id)
    if params.date_from or params.date_to:
        start, end = range_bounds(
            params.date_from or params.date_to, params.date_to or params.date_from
        )
        stmt = stmt.where(Reservation.starts_at >= start, Reservation.starts_at < end)
    term = search_filter(
        params.search,
        Reservation.customer_name,
        Reservation.customer_phone,
        Reservation.tracking_code,
    )
    if term is not None:
        stmt = stmt.where(term)

    stmt = apply_sort(
        stmt, params.sort, RESERVATION_SORTS, default="startsAt", tiebreaker=Reservation.id
    )
    return await paginate(session, stmt, params, ReservationOut)


def _booked(starts_at: datetime, ends_at: datetime, exclude_id: int | None = None):
    """Tables that already have a booking overlapping [starts_at, ends_at)."""
    stmt = select(Reservation.table_id).where(
        Reservation.table_id.is_not(None),
        Reservation.status.in_(HOLDS_TABLE),
        Reservation.starts_at < ends_at,
        Reservation.ends_at > starts_at,
    )
    if exclude_id is not None:
        stmt = stmt.where(Reservation.id != exclude_id)
    return stmt


async def free_tables(
    session: AsyncSession,
    starts_at: datetime,
    ends_at: datetime,
    party_size: int,
    exclude_id: int | None = None,
) -> list[DiningTable]:
    """Active tables big enough for the party and not booked then, smallest first so
    a couple doesn't take the table for eight."""
    tables = await session.scalars(
        select(DiningTable)
        .where(
            DiningTable.is_active.is_(True),
            DiningTable.seats >= party_size,
            DiningTable.id.not_in(_booked(starts_at, ends_at, exclude_id)),
        )
        .order_by(DiningTable.seats, DiningTable.number)
    )
    return list(tables)


async def availability(session: AsyncSession, params: AvailabilityParams) -> Availability:
    minutes = params.minutes or (await get_restaurant(session)).reservation_minutes
    ends_at = params.starts_at + timedelta(minutes=minutes)
    tables = await free_tables(
        session, params.starts_at, ends_at, params.party_size, params.reservation_id
    )
    return Availability(
        starts_at=params.starts_at,
        ends_at=ends_at,
        party_size=params.party_size,
        tables=[FreeTable.model_validate(table) for table in tables],
    )


async def assign_table(
    session: AsyncSession, reservation: Reservation, table_id: int | None
) -> None:
    """Checks the given table can take the booking, or picks the best free one."""
    starts_at, ends_at = reservation.starts_at, reservation.ends_at
    if table_id is None:
        tables = await free_tables(
            session, starts_at, ends_at, reservation.party_size, reservation.id
        )
        if not tables:
            raise ConflictError(
                f"No table for {reservation.party_size} is free at that time",
                code="no_table_available",
            )
        reservation.table_id = tables[0].id
        return

    table = await session.get(DiningTable, table_id)
    if table is None or not table.is_active:
        raise BadRequestError("The table doesn't exist or is inactive", code="invalid_table")
    if table.seats < reservation.party_size:
        raise ConflictError(
            f"Table {table.number} only seats {table.seats}", code="table_too_small"
        )
    booked = await session.scalar(
        _booked(starts_at, ends_at, reservation.id).where(Reservation.table_id == table.id)
    )
    if booked is not None:
        raise ConflictError(
            f"Table {table.number} is already booked at that time", code="table_not_available"
        )
    reservation.table_id = table.id


async def save_booking(session: AsyncSession) -> None:
    # the checks above can't see a booking made a moment ago in another request, the
    # exclusion constraint can
    await commit_or_conflict(
        session, "Someone just booked that table, please pick another", "table_not_available"
    )


def _check_not_past(starts_at: datetime) -> None:
    if starts_at < utcnow() - PAST_GRACE:
        raise BadRequestError("The booking time is in the past", code="reservation_in_past")


async def create_reservation(
    session: AsyncSession, actor: User, data: ReservationCreate
) -> Reservation:
    """Bookings taken by staff, e.g. on the phone. They are confirmed straight away."""
    _check_not_past(data.starts_at)
    minutes = data.minutes or (await get_restaurant(session)).reservation_minutes
    reservation = Reservation(
        source=ReservationSource.STAFF,
        status=ReservationStatus.CONFIRMED,
        party_size=data.party_size,
        starts_at=data.starts_at,
        ends_at=data.starts_at + timedelta(minutes=minutes),
        customer_name=data.customer_name,
        customer_phone=data.customer_phone,
        customer_email=data.customer_email,
        notes=data.notes,
        created_by_id=actor.id,
    )
    await assign_table(session, reservation, data.table_id)
    session.add(reservation)
    await save_booking(session)
    return await get_reservation(session, reservation.id)
