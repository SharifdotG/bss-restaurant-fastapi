from datetime import datetime, time, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutils import business_date, restaurant_tz, utcnow
from app.models import DiningTable, Reservation, User, UserRole
from tests.conftest import UserFactory, auth_header

pytestmark = pytest.mark.anyio

TOMORROW = business_date() + timedelta(days=1)


def at(hour: int, minute: int = 0, days: int = 1) -> datetime:
    day = business_date() + timedelta(days=days)
    return datetime.combine(day, time(hour, minute), tzinfo=restaurant_tz())


@pytest.fixture
async def manager(make_user: UserFactory) -> User:
    return await make_user(UserRole.MANAGER)


@pytest.fixture
async def tables(session: AsyncSession) -> dict[str, DiningTable]:
    tables = {"two": DiningTable(number="T2", seats=2), "four": DiningTable(number="T4", seats=4)}
    session.add_all(tables.values())
    await session.commit()
    return tables


async def settings(client: AsyncClient, manager: User, **changes) -> None:
    response = await client.patch("/restaurant", headers=auth_header(manager), json=changes)
    assert response.status_code == 200, response.text


@pytest.fixture
async def open_for_bookings(client: AsyncClient, manager: User, tables) -> None:
    await settings(client, manager, acceptsReservations=True)


async def request(client: AsyncClient, expect: int = 201, **overrides) -> dict:
    body = {
        "startsAt": at(19).isoformat(),
        "partySize": 2,
        "customerName": "Karim",
        "customerPhone": "01811 222333",
    } | overrides
    response = await client.post("/public/reservations", json=body)
    assert response.status_code == expect, response.text
    return response.json()


async def slots(client: AsyncClient, party_size: int = 2, day=TOMORROW) -> list[str]:
    response = await client.get(
        "/public/reservations/slots", params={"day": day.isoformat(), "partySize": party_size}
    )
    assert response.status_code == 200, response.text
    return [
        datetime.fromisoformat(s["startsAt"]).strftime("%H:%M") for s in response.json()["slots"]
    ]


def booking(table: DiningTable, start: datetime, status: str = "confirmed") -> Reservation:
    return Reservation(
        source="staff",
        status=status,
        table_id=table.id,
        party_size=2,
        starts_at=start,
        ends_at=start + timedelta(minutes=90),
        customer_name="x",
        customer_phone="0171",
    )


async def test_switched_off_by_default(client: AsyncClient, tables) -> None:
    response = await client.get(
        "/public/reservations/slots", params={"day": TOMORROW.isoformat(), "partySize": 2}
    )
    assert response.json()["code"] == "reservations_disabled"
    assert (await request(client, 409))["code"] == "reservations_disabled"

    response = await client.get("/public/restaurant")
    assert response.json()["acceptsReservations"] is False
    assert response.json()["opensAt"] == "11:00:00"


# slots


async def test_slots_follow_opening_hours_and_bookings(
    client: AsyncClient, session: AsyncSession, tables, open_for_bookings
) -> None:
    # open 11 to 23, 90 minute bookings, so the last one starts at 21:30
    every = await slots(client)
    assert every[0] == "11:00"
    assert every[-1] == "21:30"
    assert len(every) == 22

    # both tables taken at 19:00, anything overlapping 19:00-20:30 is gone
    session.add_all([booking(tables["two"], at(19)), booking(tables["four"], at(19))])
    session.add(booking(tables["four"], at(12), status="cancelled"))
    await session.commit()
    left = await slots(client)
    assert "17:30" in left
    assert not {"18:00", "18:30", "19:00", "19:30", "20:00"} & set(left)
    assert "20:30" in left

    assert await slots(client, party_size=5) == []
    assert await slots(client, day=TOMORROW + timedelta(days=90)) == []
    assert await slots(client, day=TOMORROW - timedelta(days=2)) == []


async def test_open_past_midnight(
    client: AsyncClient, manager: User, tables, open_for_bookings
) -> None:
    await settings(client, manager, opensAt="18:00", closesAt="02:00")
    times = await slots(client)
    assert times[0] == "18:00"
    assert times[-1] == "00:30"

    booked = await request(client, startsAt=at(23, 30).isoformat())
    assert datetime.fromisoformat(booked["endsAt"]) == at(1, days=2)
    error = await request(client, 400, startsAt=at(1, days=2).isoformat())
    assert error["code"] == "outside_opening_hours"


# booking


async def test_request_waits_for_the_staff(
    client: AsyncClient, manager: User, tables, open_for_bookings
) -> None:
    booked = await request(client, partySize=3, notes="window please")
    assert booked["status"] == "requested"
    assert booked["table"] is None
    assert booked["canCancel"] is True
    assert "customerPhone" not in booked

    headers = auth_header(manager)
    response = await client.get("/reservations", headers=headers, params={"status": "requested"})
    [staff_view] = response.json()["items"]
    assert staff_view["source"] == "online"
    assert staff_view["customerPhone"] == "01811222333"

    response = await client.post(
        f"/reservations/{staff_view['id']}/status", headers=headers, json={"status": "confirmed"}
    )
    assert response.json()["table"]["number"] == "T4"

    response = await client.get(f"/public/reservations/{booked['trackingCode']}")
    assert response.json()["status"] == "confirmed"
    assert response.json()["table"] == {"number": "T4", "location": None}


async def test_auto_confirm_gives_a_table_straight_away(
    client: AsyncClient, manager: User, tables, open_for_bookings
) -> None:
    await settings(client, manager, autoConfirmReservations=True)
    booked = await request(client)
    assert booked["status"] == "confirmed"
    assert booked["table"]["number"] == "T2"


async def test_when_bookings_are_refused(
    client: AsyncClient, session: AsyncSession, tables, open_for_bookings
) -> None:
    soon = utcnow() + timedelta(minutes=30)
    assert (await request(client, 400, startsAt=soon.isoformat()))["code"] == "too_short_notice"
    far = at(19, days=90).isoformat()
    assert (await request(client, 400, startsAt=far))["code"] == "too_far_ahead"
    error = await request(client, 400, startsAt=at(22).isoformat())
    assert error["code"] == "outside_opening_hours"
    assert error["closesAt"] == "23:00:00"
    assert (await request(client, 400, startsAt=at(9).isoformat()))["code"] == (
        "outside_opening_hours"
    )

    session.add(booking(tables["four"], at(19)))
    await session.commit()
    error = await request(client, 409, partySize=3)
    assert error["code"] == "no_table_available"

    await request(client, 422, partySize=21)
    await request(client, 422, startsAt="2030-01-01T19:00:00")


async def test_bookings_per_phone_are_limited(client: AsyncClient, open_for_bookings) -> None:
    for day in (1, 2, 3):
        await request(client, startsAt=at(19, days=day).isoformat())
    error = await request(client, 409, startsAt=at(19, days=4).isoformat())
    assert error["code"] == "too_many_bookings"
    # someone else is fine
    await request(client, startsAt=at(19, days=4).isoformat(), customerPhone="01911000000")


async def test_customer_cancels(client: AsyncClient, open_for_bookings) -> None:
    booked = await request(client)
    code = booked["trackingCode"]

    response = await client.post(f"/public/reservations/{code}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["cancelReason"] == "Cancelled by the customer"
    assert response.json()["canCancel"] is False

    response = await client.post(f"/public/reservations/{code}/cancel")
    assert response.json()["code"] == "cancel_not_allowed"

    assert (await client.get("/public/reservations/nope")).status_code == 404
