from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import CurrentUser, SessionDep, require_roles
from app.models import Reservation, User, UserRole
from app.schemas.common import Page
from app.schemas.reservation import (
    Availability,
    AvailabilityParams,
    ReservationCreate,
    ReservationListParams,
    ReservationOut,
)
from app.services import reservations as reservation_service

router = APIRouter(prefix="/reservations", tags=["reservations"])

FrontOfHouse = Annotated[
    User, Depends(require_roles(UserRole.MANAGER, UserRole.WAITER, UserRole.CASHIER))
]


@router.get("", response_model=Page[ReservationOut])
async def list_reservations(
    session: SessionDep, _: CurrentUser, params: Annotated[ReservationListParams, Query()]
) -> Page[ReservationOut]:
    """Sorted by booking time, filter with `dateFrom`/`dateTo` for a day's bookings."""
    return await reservation_service.list_reservations(session, params)


@router.get("/availability", response_model=Availability)
async def availability(
    session: SessionDep, _: CurrentUser, params: Annotated[AvailabilityParams, Query()]
) -> Availability:
    """Tables free for a party at a given time."""
    return await reservation_service.availability(session, params)


@router.post("", response_model=ReservationOut, status_code=status.HTTP_201_CREATED)
async def create_reservation(
    body: ReservationCreate, session: SessionDep, actor: FrontOfHouse
) -> Reservation:
    """Books a table, confirmed straight away. Without `tableId` the smallest free table
    that fits is picked."""
    return await reservation_service.create_reservation(session, actor, body)


@router.get("/{reservation_id}", response_model=ReservationOut)
async def get_reservation(reservation_id: int, session: SessionDep, _: CurrentUser) -> Reservation:
    return await reservation_service.get_reservation(session, reservation_id)
