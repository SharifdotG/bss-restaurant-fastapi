from datetime import datetime, time, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutils import business_date, restaurant_tz
from app.models import DiningTable, Reservation, User, UserRole
from tests.conftest import UserFactory, auth_header

pytestmark = pytest.mark.anyio


def at(hour: int, minute: int = 0, days: int = 1) -> datetime:
    """A local time `days` from today."""
    day = business_date() + timedelta(days=days)
    return datetime.combine(day, time(hour, minute), tzinfo=restaurant_tz())


@pytest.fixture
async def tables(session: AsyncSession) -> dict[str, DiningTable]:
    tables = {
        "two": DiningTable(number="T2", seats=2),
        "four": DiningTable(number="T4", seats=4, location="Window"),
        "eight": DiningTable(number="T8", seats=8),
        "closed": DiningTable(number="T9", seats=6, is_active=False),
    }
    session.add_all(tables.values())
    await session.commit()
    return tables


@pytest.fixture
async def waiter(make_user: UserFactory) -> User:
    return await make_user(UserRole.WAITER, first_name="Wes", last_name="Lee")


@pytest.fixture
async def manager_headers(make_user: UserFactory) -> dict:
    return auth_header(await make_user(UserRole.MANAGER))


async def book(client: AsyncClient, user: User, expect: int = 201, **overrides) -> dict:
    body = {
        "startsAt": at(19).isoformat(),
        "partySize": 2,
        "customerName": "Rahim",
        "customerPhone": "01711-000000",
    } | overrides
    response = await client.post("/reservations", headers=auth_header(user), json=body)
    assert response.status_code == expect, response.text
    return response.json()


# booking


async def test_staff_booking_is_confirmed_on_the_smallest_table(
    client: AsyncClient, waiter: User, tables: dict[str, DiningTable]
) -> None:
    booking = await book(client, waiter, partySize=3, notes="birthday")

    assert booking["status"] == "confirmed"
    assert booking["source"] == "staff"
    assert booking["table"]["number"] == "T4"
    assert booking["minutes"] == 90
    assert booking["customerPhone"] == "01711000000"
    assert booking["createdBy"]["fullName"] == "Wes Lee"
    assert booking["nextStatuses"] == ["seated", "no_show", "cancelled"]
    assert len(booking["trackingCode"]) >= 16
    assert datetime.fromisoformat(booking["endsAt"]) == at(20, 30)


async def test_booking_length_comes_from_the_settings(
    client: AsyncClient, waiter: User, manager_headers: dict, tables: dict[str, DiningTable]
) -> None:
    await client.patch("/restaurant", headers=manager_headers, json={"reservationMinutes": 120})
    assert (await book(client, waiter))["minutes"] == 120
    assert (await book(client, waiter, minutes=45))["minutes"] == 45


async def test_chosen_table_must_fit(
    client: AsyncClient, waiter: User, tables: dict[str, DiningTable]
) -> None:
    error = await book(client, waiter, 409, partySize=5, tableId=tables["four"].id)
    assert error["code"] == "table_too_small"

    error = await book(client, waiter, 400, tableId=tables["closed"].id)
    assert error["code"] == "invalid_table"

    booking = await book(client, waiter, partySize=2, tableId=tables["eight"].id)
    assert booking["table"]["number"] == "T8"


async def test_a_table_cannot_be_booked_twice(
    client: AsyncClient, waiter: User, tables: dict[str, DiningTable]
) -> None:
    four = tables["four"].id
    await book(client, waiter, tableId=four)

    error = await book(client, waiter, 409, tableId=four, startsAt=at(20).isoformat())
    assert error["code"] == "table_not_available"

    # right after the first one ends is fine
    await book(client, waiter, tableId=four, startsAt=at(20, 30).isoformat())
    await book(client, waiter, tableId=four, startsAt=at(19, days=2).isoformat())


async def test_next_free_table_is_picked_until_none_is_left(
    client: AsyncClient, waiter: User, tables: dict[str, DiningTable]
) -> None:
    picked = [(await book(client, waiter, partySize=2))["table"]["number"] for _ in range(3)]
    assert picked == ["T2", "T4", "T8"]

    error = await book(client, waiter, 409, partySize=2)
    assert error["code"] == "no_table_available"


async def test_the_database_refuses_overlapping_bookings(
    session: AsyncSession, tables: dict[str, DiningTable]
) -> None:
    # what protects two requests racing for the same table
    def booking(status: str, start: datetime) -> Reservation:
        return Reservation(
            source="staff",
            status=status,
            table_id=tables["four"].id,
            party_size=2,
            starts_at=start,
            ends_at=start + timedelta(hours=1),
            customer_name="x",
            customer_phone="0171",
        )

    session.add_all([booking("confirmed", at(19)), booking("cancelled", at(19, 30))])
    await session.commit()

    session.add(booking("seated", at(19, 30)))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_invalid_bookings(
    client: AsyncClient, waiter: User, tables: dict[str, DiningTable]
) -> None:
    error = await book(client, waiter, 400, startsAt=at(19, days=-1).isoformat())
    assert error["code"] == "reservation_in_past"

    # no offset, we wouldn't know which 7pm
    await book(client, waiter, 422, startsAt="2030-01-01T19:00:00")
    await book(client, waiter, 422, partySize=0)
    await book(client, waiter, 422, minutes=600)
    await book(client, waiter, 422, customerPhone="abc")


async def test_chef_cannot_book(
    client: AsyncClient, make_user: UserFactory, tables: dict[str, DiningTable]
) -> None:
    chef = await make_user(UserRole.CHEF)
    await book(client, chef, 403)


# finding tables


async def test_availability(
    client: AsyncClient, waiter: User, tables: dict[str, DiningTable]
) -> None:
    booking = await book(client, waiter, partySize=2)

    async def free(**params) -> list[str]:
        query = {"startsAt": at(19, 30).isoformat(), "partySize": 2} | params
        response = await client.get(
            "/reservations/availability", headers=auth_header(waiter), params=query
        )
        assert response.status_code == 200, response.text
        return [t["number"] for t in response.json()["tables"]]

    assert await free() == ["T4", "T8"]
    assert await free(partySize=5) == ["T8"]
    assert await free(startsAt=at(21).isoformat()) == ["T2", "T4", "T8"]
    # moving a booking, it shouldn't stand in its own way
    assert await free(reservationId=booking["id"]) == ["T2", "T4", "T8"]


async def test_list_bookings(
    client: AsyncClient, waiter: User, tables: dict[str, DiningTable]
) -> None:
    await book(client, waiter, customerName="Late", startsAt=at(21).isoformat())
    await book(client, waiter, customerName="Early", startsAt=at(18).isoformat())
    await book(client, waiter, customerName="Next week", startsAt=at(19, days=7).isoformat())
    headers = auth_header(waiter)

    tomorrow = (business_date() + timedelta(days=1)).isoformat()
    response = await client.get("/reservations", headers=headers, params={"dateFrom": tomorrow})
    assert [r["customerName"] for r in response.json()["items"]] == ["Early", "Late"]

    response = await client.get("/reservations", headers=headers, params={"search": "week"})
    assert response.json()["total"] == 1

    response = await client.get("/reservations", headers=headers, params={"sort": "-startsAt"})
    assert response.json()["items"][0]["customerName"] == "Next week"


# changing bookings


async def move(client: AsyncClient, user: User, booking: dict, expect: int = 200, **body) -> dict:
    response = await client.post(
        f"/reservations/{booking['id']}/status", headers=auth_header(user), json=body
    )
    assert response.status_code == expect, response.text
    return response.json()


async def edit(client: AsyncClient, user: User, booking: dict, expect: int = 200, **body) -> dict:
    response = await client.patch(
        f"/reservations/{booking['id']}", headers=auth_header(user), json=body
    )
    assert response.status_code == expect, response.text
    return response.json()


async def test_guests_arrive_and_leave(
    client: AsyncClient, waiter: User, tables: dict[str, DiningTable]
) -> None:
    booking = await book(client, waiter)

    seated = await move(client, waiter, booking, status="seated")
    assert seated["nextStatuses"] == ["completed"]
    done = await move(client, waiter, seated, status="completed")
    assert done["nextStatuses"] == []

    # the table is free again for that time
    again = await book(client, waiter, tableId=booking["table"]["id"])
    assert again["status"] == "confirmed"


async def test_cancelling_frees_the_table_and_needs_a_reason(
    client: AsyncClient, waiter: User, tables: dict[str, DiningTable]
) -> None:
    booking = await book(client, waiter, tableId=tables["two"].id)

    error = await move(client, waiter, booking, 400, status="cancelled", note=" ")
    assert error["code"] == "reason_required"
    cancelled = await move(client, waiter, booking, status="cancelled", note="called to cancel")
    assert cancelled["cancelReason"] == "called to cancel"

    await book(client, waiter, tableId=tables["two"].id)
    error = await move(client, waiter, cancelled, 409, status="confirmed")
    assert error["code"] == "invalid_status_change"


async def test_no_show_only_after_the_booking_time(
    client: AsyncClient, waiter: User, session: AsyncSession, tables: dict[str, DiningTable]
) -> None:
    booking = await book(client, waiter)
    error = await move(client, waiter, booking, 409, status="no_show")
    assert error["code"] == "too_early"

    started = await book(client, waiter, startsAt=at(12).isoformat())
    # pretend it was for yesterday, staff can't book in the past
    row = await session.get(Reservation, started["id"])
    row.starts_at -= timedelta(days=2)
    row.ends_at -= timedelta(days=2)
    await session.commit()
    assert (await move(client, waiter, started, status="no_show"))["status"] == "no_show"


async def test_table_only_goes_with_confirming(
    client: AsyncClient, waiter: User, tables: dict[str, DiningTable]
) -> None:
    booking = await book(client, waiter)
    await move(client, waiter, booking, 422, status="seated", tableId=tables["eight"].id)


async def test_move_a_booking(
    client: AsyncClient, waiter: User, tables: dict[str, DiningTable]
) -> None:
    first = await book(client, waiter, tableId=tables["four"].id)
    second = await book(
        client, waiter, tableId=tables["four"].id, startsAt=at(21).isoformat(), minutes=60
    )

    # later, keeps its own table and length
    moved = await edit(client, waiter, first, startsAt=at(19, 15).isoformat(), notes=None)
    assert moved["table"]["number"] == "T4"
    assert datetime.fromisoformat(moved["endsAt"]) == at(20, 45)

    # would run into the second booking
    error = await edit(client, waiter, first, 409, minutes=120)
    assert error["code"] == "table_not_available"

    # more people than the table seats
    error = await edit(client, waiter, second, 409, partySize=6)
    assert error["code"] == "table_too_small"
    bigger = await edit(client, waiter, second, partySize=6, tableId=tables["eight"].id)
    assert bigger["table"]["number"] == "T8"
    assert bigger["minutes"] == 60


async def test_finished_bookings_cannot_be_edited(
    client: AsyncClient, waiter: User, tables: dict[str, DiningTable]
) -> None:
    booking = await book(client, waiter)
    await move(client, waiter, booking, status="seated")
    error = await edit(client, waiter, booking, 409, partySize=3)
    assert error["code"] == "reservation_closed"


async def test_dashboard_shows_todays_bookings(
    client: AsyncClient, session: AsyncSession, tables: dict[str, DiningTable], manager_headers
) -> None:
    def booking(status: str, start: datetime, party: int, table: str | None = "four"):
        return Reservation(
            source="staff",
            status=status,
            table_id=tables[table].id if table else None,
            party_size=party,
            starts_at=start,
            ends_at=start + timedelta(hours=1),
            customer_name="x",
            customer_phone="0171",
        )

    session.add_all(
        [
            booking("completed", at(12, days=0), 3),
            booking("confirmed", at(20, days=0), 4),
            booking("cancelled", at(20, days=0), 2),
            booking("confirmed", at(20), 2),
            booking("requested", at(13), 2, table=None),
        ]
    )
    await session.commit()

    body = (await client.get("/dashboard", headers=manager_headers)).json()
    assert body["reservations"] == {"today": 2, "guestsToday": 7, "requests": 1}
