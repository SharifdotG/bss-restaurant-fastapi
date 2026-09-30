from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutils import business_date
from app.models import Category, DiningTable, Employee, Food, User, UserRole
from tests.conftest import UserFactory, auth_header

pytestmark = pytest.mark.anyio


@pytest.fixture
async def menu(session: AsyncSession) -> dict[str, Food]:
    burgers = Category(name="Burgers")
    foods = {
        "burger": Food(name="Beef Burger", price=Decimal("350"), category=burgers),
        "fries": Food(
            name="Fries", price=Decimal("120"), discount_type="percentage", discount_value=10
        ),
        "coke": Food(name="Coke", price=Decimal("60"), discount_type="flat", discount_value=5),
        "soup": Food(name="Soup", price=Decimal("200"), is_available=False),
    }
    session.add_all(foods.values())
    await session.commit()
    return foods


@pytest.fixture
async def table(session: AsyncSession) -> DiningTable:
    table = DiningTable(number="T1", seats=4)
    session.add(table)
    await session.commit()
    return table


@pytest.fixture
async def waiter(make_user: UserFactory, session: AsyncSession) -> User:
    user = await make_user(UserRole.WAITER, first_name="Wes", last_name="Lee")
    session.add(
        Employee(
            user_id=user.id,
            first_name="Wes",
            last_name="Lee",
            designation="Waiter",
            join_date=business_date(),
        )
    )
    await session.commit()
    return user


async def place_order(client: AsyncClient, user: User, **overrides) -> dict:
    response = await client.post("/orders", headers=auth_header(user), json=overrides)
    assert response.status_code == 201, response.text
    return response.json()


# creating


async def test_prices_come_from_the_menu(
    client: AsyncClient, waiter: User, table: DiningTable, menu: dict[str, Food]
) -> None:
    order = await place_order(
        client,
        waiter,
        tableId=table.id,
        items=[
            {"foodId": menu["burger"].id, "quantity": 2},
            {"foodId": menu["fries"].id, "quantity": 1, "notes": "extra salt"},
            {"foodId": menu["coke"].id, "quantity": 3},
            # extra fields like prices are simply ignored
            {"foodId": menu["burger"].id, "quantity": 1, "unitPrice": 1},
        ],
    )

    lines = {(i["foodName"], i["notes"]): i for i in order["items"]}
    assert lines[("Beef Burger", None)]["quantity"] == 3
    assert lines[("Beef Burger", None)]["lineTotal"] == 1050
    assert lines[("Fries", "extra salt")]["finalUnitPrice"] == 108
    assert lines[("Coke", None)]["unitDiscount"] == 5
    assert order["subtotal"] == 350 * 3 + 120 + 60 * 3
    assert order["discountTotal"] == 12 + 15
    assert order["total"] == 1050 + 108 + 165
    assert order["itemCount"] == 7
    assert order["status"] == "pending"
    assert order["waiter"]["fullName"] == "Wes Lee"
    assert order["table"] == {"id": table.id, "number": "T1"}


async def test_order_numbers_count_up_per_day(
    client: AsyncClient, waiter: User, table: DiningTable, menu: dict[str, Food]
) -> None:
    items = [{"foodId": menu["coke"].id, "quantity": 1}]
    first = await place_order(client, waiter, tableId=table.id, items=items)
    second = await place_order(client, waiter, orderType="takeaway", items=items)

    prefix = business_date().strftime("%y%m%d")
    assert first["orderNumber"] == f"{prefix}-0001"
    assert second["orderNumber"] == f"{prefix}-0002"


async def test_unknown_and_unavailable_foods(
    client: AsyncClient, waiter: User, table: DiningTable, menu: dict[str, Food]
) -> None:
    unknown = await client.post(
        "/orders",
        headers=auth_header(waiter),
        json={"tableId": table.id, "items": [{"foodId": 999, "quantity": 1}]},
    )
    assert unknown.json()["code"] == "unknown_foods"
    assert unknown.json()["foodIds"] == [999]

    sold_out = await client.post(
        "/orders",
        headers=auth_header(waiter),
        json={"tableId": table.id, "items": [{"foodId": menu["soup"].id, "quantity": 1}]},
    )
    assert sold_out.json()["code"] == "foods_unavailable"


@pytest.mark.parametrize(
    "payload",
    [
        {"orderType": "dine_in", "items": [{"foodId": 1, "quantity": 1}]},
        {"orderType": "takeaway", "tableId": 1, "items": [{"foodId": 1, "quantity": 1}]},
        {"orderType": "takeaway", "items": []},
        {"orderType": "takeaway", "items": [{"foodId": 1, "quantity": 0}]},
    ],
)
async def test_invalid_orders(client: AsyncClient, waiter: User, payload: dict) -> None:
    response = await client.post("/orders", headers=auth_header(waiter), json=payload)

    assert response.status_code == 422


async def test_chef_cannot_take_orders(
    client: AsyncClient, make_user: UserFactory, menu: dict[str, Food]
) -> None:
    chef = await make_user(UserRole.CHEF)

    response = await client.post(
        "/orders",
        headers=auth_header(chef),
        json={"orderType": "takeaway", "items": [{"foodId": menu["coke"].id, "quantity": 1}]},
    )

    assert response.status_code == 403


async def test_list_orders(
    client: AsyncClient, waiter: User, table: DiningTable, menu: dict[str, Food]
) -> None:
    items = [{"foodId": menu["coke"].id, "quantity": 1}]
    await place_order(client, waiter, tableId=table.id, items=items)
    await place_order(client, waiter, orderType="takeaway", customerName="Nadia", items=items)
    headers = auth_header(waiter)

    everything = (await client.get("/orders", headers=headers)).json()
    assert everything["total"] == 2
    assert everything["items"][0]["customerName"] == "Nadia"

    takeaway = (await client.get("/orders?orderType=takeaway", headers=headers)).json()
    assert takeaway["total"] == 1
    found = (await client.get("/orders?search=nadia", headers=headers)).json()
    assert found["total"] == 1
    at_table = (await client.get(f"/orders?tableId={table.id}", headers=headers)).json()
    assert at_table["total"] == 1
    today = business_date().isoformat()
    by_date = (await client.get(f"/orders?dateFrom={today}&dateTo={today}", headers=headers)).json()
    assert by_date["total"] == 2
    pending = (await client.get("/orders?status=pending&status=confirmed", headers=headers)).json()
    assert pending["total"] == 2


async def test_table_shows_as_occupied(
    client: AsyncClient, waiter: User, table: DiningTable, menu: dict[str, Food]
) -> None:
    headers = auth_header(waiter)
    assert (await client.get(f"/tables/{table.id}", headers=headers)).json()["isOccupied"] is False

    await place_order(
        client, waiter, tableId=table.id, items=[{"foodId": menu["coke"].id, "quantity": 1}]
    )

    assert (await client.get(f"/tables/{table.id}", headers=headers)).json()["isOccupied"] is True


# status flow


async def move(client: AsyncClient, user: User, order: dict, status: str, note: str | None = None):
    return await client.post(
        f"/orders/{order['id']}/status",
        headers=auth_header(user),
        json={"status": status, "note": note},
    )


@pytest.fixture
async def order(
    client: AsyncClient, waiter: User, table: DiningTable, menu: dict[str, Food]
) -> dict:
    return await place_order(
        client, waiter, tableId=table.id, items=[{"foodId": menu["burger"].id, "quantity": 1}]
    )


async def test_full_happy_path(
    client: AsyncClient, make_user: UserFactory, waiter: User, order: dict
) -> None:
    chef = await make_user(UserRole.CHEF)
    cashier = await make_user(UserRole.CASHIER)
    steps = [
        (waiter, "confirmed"),
        (chef, "preparing"),
        (chef, "ready"),
        (waiter, "served"),
        (cashier, "paid"),
    ]

    for user, status in steps:
        response = await move(client, user, order, status)
        assert response.status_code == 200, response.text

    body = response.json()
    assert body["status"] == "paid"
    assert body["nextStatuses"] == []
    assert body["closedAt"] is not None
    assert [e["toStatus"] for e in body["history"]] == [
        "pending",
        "confirmed",
        "preparing",
        "ready",
        "served",
        "paid",
    ]
    assert body["history"][2]["changedBy"]["id"] == chef.id


async def test_steps_cannot_be_skipped(client: AsyncClient, waiter: User, order: dict) -> None:
    response = await move(client, waiter, order, "served")

    assert response.status_code == 409
    assert response.json()["code"] == "invalid_status_change"
    assert response.json()["allowed"] == ["confirmed", "cancelled"]


async def test_unknown_status_is_rejected(client: AsyncClient, waiter: User, order: dict) -> None:
    # the old api silently turned typos into "pending"
    response = await move(client, waiter, order, "done")

    assert response.status_code == 422


@pytest.mark.parametrize(("role", "status"), [(UserRole.WAITER, "preparing")])
async def test_roles_per_step(
    client: AsyncClient,
    make_user: UserFactory,
    waiter: User,
    order: dict,
    role: UserRole,
    status: str,
) -> None:
    await move(client, waiter, order, "confirmed")
    user = await make_user(role)

    response = await move(client, user, order, status)

    assert response.status_code == 403


async def test_cancel_needs_a_reason(client: AsyncClient, waiter: User, order: dict) -> None:
    no_reason = await move(client, waiter, order, "cancelled")
    assert no_reason.json()["code"] == "reason_required"

    response = await move(client, waiter, order, "cancelled", "customer left")
    assert response.json()["status"] == "cancelled"
    assert response.json()["cancelReason"] == "customer left"

    again = await move(client, waiter, order, "confirmed")
    assert again.status_code == 409


async def test_only_manager_cancels_while_cooking(
    client: AsyncClient, make_user: UserFactory, waiter: User, order: dict
) -> None:
    chef = await make_user(UserRole.CHEF)
    manager = await make_user(UserRole.MANAGER)
    await move(client, waiter, order, "confirmed")
    await move(client, chef, order, "preparing")

    assert (await move(client, waiter, order, "cancelled", "too slow")).status_code == 403
    assert (await move(client, manager, order, "cancelled", "too slow")).status_code == 200


async def test_paid_order_frees_the_table(
    client: AsyncClient, make_user: UserFactory, waiter: User, table: DiningTable, order: dict
) -> None:
    manager = await make_user(UserRole.MANAGER)
    for status in ("confirmed", "preparing", "ready", "served", "paid"):
        await move(client, manager, order, status)

    shown = (await client.get(f"/tables/{table.id}", headers=auth_header(manager))).json()
    assert shown["isOccupied"] is False
    active = (await client.get("/orders?active=true", headers=auth_header(manager))).json()
    assert active["total"] == 0


# editing


async def test_replace_items_before_cooking(
    client: AsyncClient, make_user: UserFactory, waiter: User, order: dict, menu: dict[str, Food]
) -> None:
    url = f"/orders/{order['id']}/items"
    headers = auth_header(waiter)

    response = await client.put(
        url, headers=headers, json={"items": [{"foodId": menu["fries"].id, "quantity": 2}]}
    )
    assert [i["foodName"] for i in response.json()["items"]] == ["Fries"]
    assert response.json()["total"] == 216

    chef = await make_user(UserRole.CHEF)
    await move(client, waiter, order, "confirmed")
    await move(client, chef, order, "preparing")
    locked = await client.put(
        url, headers=headers, json={"items": [{"foodId": menu["coke"].id, "quantity": 1}]}
    )
    assert locked.json()["code"] == "order_locked"


async def test_add_items_while_cooking(
    client: AsyncClient, make_user: UserFactory, waiter: User, order: dict, menu: dict[str, Food]
) -> None:
    chef = await make_user(UserRole.CHEF)
    await move(client, waiter, order, "confirmed")
    await move(client, chef, order, "preparing")

    response = await client.post(
        f"/orders/{order['id']}/items",
        headers=auth_header(waiter),
        json={"items": [{"foodId": menu["coke"].id, "quantity": 2}]},
    )

    assert response.status_code == 200
    assert response.json()["total"] == 350 + 110
    assert len(response.json()["items"]) == 2


async def test_old_lines_keep_their_price(
    client: AsyncClient,
    session: AsyncSession,
    waiter: User,
    order: dict,
    menu: dict[str, Food],
) -> None:
    menu["burger"].price = Decimal("400")
    await session.commit()

    response = await client.post(
        f"/orders/{order['id']}/items",
        headers=auth_header(waiter),
        json={"items": [{"foodId": menu["burger"].id, "quantity": 1}]},
    )

    assert [i["unitPrice"] for i in response.json()["items"]] == [350, 400]
    assert response.json()["total"] == 750


async def test_update_order_details(
    client: AsyncClient, session: AsyncSession, waiter: User, order: dict
) -> None:
    other = DiningTable(number="T2", seats=2)
    session.add(other)
    await session.commit()

    response = await client.patch(
        f"/orders/{order['id']}",
        headers=auth_header(waiter),
        json={"tableId": other.id, "customerName": "Nadia", "customerPhone": "01711 223344"},
    )

    body = response.json()
    assert body["table"]["number"] == "T2"
    assert body["customerName"] == "Nadia"
    assert body["customerPhone"] == "01711223344"


async def test_closed_orders_cannot_be_edited(
    client: AsyncClient, waiter: User, order: dict, menu: dict[str, Food]
) -> None:
    await move(client, waiter, order, "cancelled", "wrong table")

    response = await client.patch(
        f"/orders/{order['id']}", headers=auth_header(waiter), json={"notes": "x"}
    )
    assert response.json()["code"] == "order_closed"
    added = await client.post(
        f"/orders/{order['id']}/items",
        headers=auth_header(waiter),
        json={"items": [{"foodId": menu["coke"].id, "quantity": 1}]},
    )
    assert added.json()["code"] == "order_closed"
