import logging
from enum import StrEnum
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.live import Event, hub
from app.core.timeutils import business_date, day_bounds, utcnow
from app.models import (
    ACTIVE_STATUSES,
    Order,
    Reservation,
    ReservationStatus,
)
from app.schemas.common import CamelModel
from app.schemas.live import LiveOrder, LiveReservation

logger = logging.getLogger(__name__)


class Topic(StrEnum):
    ORDERS = "orders"
    RESERVATIONS = "reservations"


def _event(topic: Topic, name: str, data: CamelModel) -> Event:
    return {
        "event": f"{topic.removesuffix('s')}.{name}",
        "topic": topic.value,
        "data": data.model_dump(mode="json", by_alias=True),
        "at": utcnow().isoformat(),
    }


async def _publish(event: Event) -> None:
    # the change is already saved, a hiccup in the live feed must not fail the request
    try:
        await hub.publish(event)
    except Exception:
        logger.exception("could not publish %s", event["event"])


async def order_created(order: Order) -> None:
    await _publish(_event(Topic.ORDERS, "created", LiveOrder.model_validate(order)))


async def order_updated(order: Order) -> None:
    await _publish(_event(Topic.ORDERS, "updated", LiveOrder.model_validate(order)))


async def reservation_created(reservation: Reservation) -> None:
    data = LiveReservation.model_validate(reservation)
    await _publish(_event(Topic.RESERVATIONS, "created", data))


async def reservation_updated(reservation: Reservation) -> None:
    data = LiveReservation.model_validate(reservation)
    await _publish(_event(Topic.RESERVATIONS, "updated", data))


async def snapshot(session: AsyncSession, topics: frozenset[str]) -> dict[str, Any]:
    """What a screen needs to start from: open orders, and today's bookings plus the
    requests nobody has answered yet."""
    result: dict[str, Any] = {"event": "snapshot", "at": utcnow().isoformat()}
    if Topic.ORDERS in topics:
        orders = await session.scalars(
            select(Order)
            .options(
                selectinload(Order.items), selectinload(Order.table), selectinload(Order.waiter)
            )
            .where(Order.status.in_(ACTIVE_STATUSES))
            .order_by(Order.created_at, Order.id)
        )
        result["orders"] = [
            LiveOrder.model_validate(order).model_dump(mode="json", by_alias=True)
            for order in orders
        ]
    if Topic.RESERVATIONS in topics:
        start, end = day_bounds(business_date())
        reservations = await session.scalars(
            select(Reservation)
            .options(selectinload(Reservation.table))
            .where(
                or_(
                    Reservation.status == ReservationStatus.SEATED,
                    (Reservation.status == ReservationStatus.CONFIRMED)
                    & (Reservation.starts_at >= start)
                    & (Reservation.starts_at < end),
                    (Reservation.status == ReservationStatus.REQUESTED)
                    & (Reservation.ends_at > utcnow()),
                )
            )
            .order_by(Reservation.starts_at, Reservation.id)
        )
        result["reservations"] = [
            LiveReservation.model_validate(r).model_dump(mode="json", by_alias=True)
            for r in reservations
        ]
    return result
