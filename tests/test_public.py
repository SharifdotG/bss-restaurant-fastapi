from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.timeutils import business_date, utcnow
from app.models import Category, DiningTable, Employee, Food, User, UserRole
from tests.conftest import UserFactory, auth_header

pytestmark = pytest.mark.anyio


@pytest.fixture
async def manager(make_user: UserFactory) -> User:
    return await make_user(UserRole.MANAGER)


@pytest.fixture
async def tea(session: AsyncSession) -> Food:
    food = Food(name="Tea", price=Decimal("20"))
    session.add(food)
    await session.commit()
    return food


@pytest.fixture
async def table(session: AsyncSession) -> DiningTable:
    table = DiningTable(number="T7", seats=4, location="Rooftop")
    session.add(table)
    await session.commit()
    return table


async def switch(client: AsyncClient, manager: User, **flags) -> None:
    response = await client.patch("/restaurant", headers=auth_header(manager), json=flags)
    assert response.status_code == 200, response.text


def order_body(food: Food, quantity: int = 1, **extra) -> dict:
    return {"items": [{"foodId": food.id, "quantity": quantity}], **extra}


ONLINE_CUSTOMER = {"customerName": "Mina", "customerPhone": "01711112222"}


# menu


async def test_menu_without_logging_in(client: AsyncClient, session: AsyncSession) -> None:
    mains = Category(name="Mains", sort_order=1)
    drinks = Category(name="Drinks", sort_order=2)
    hidden = Category(name="Staff meals", is_active=False)
    empty = Category(name="Desserts")
    session.add_all([mains, drinks, hidden, empty])
    await session.flush()
    session.add_all(
        [
            Food(name="Beef Curry", price=Decimal("300"), category_id=mains.id),
            Food(name="Kacchi", price=Decimal("400"), category_id=mains.id, is_featured=True),
            Food(
                name="Sold Out Soup", price=Decimal("150"), category_id=mains.id, is_available=False
            ),
            Food(name="Lassi", price=Decimal("90"), category_id=drinks.id),
            Food(name="Old Lassi", price=Decimal("80"), category_id=drinks.id, deleted_at=utcnow()),
            Food(name="Rice for staff", price=Decimal("10"), category_id=hidden.id),
            Food(name="Water", price=Decimal("20")),
        ]
    )
    await session.commit()

    response = await client.get("/public/menu")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=60"
    body = response.json()
    assert body["restaurant"]["currency"] == "BDT"
    assert [c["name"] for c in body["categories"]] == ["Mains", "Drinks"]
    mains_foods = body["categories"][0]["foods"]
    # featured first
    assert [f["name"] for f in mains_foods] == ["Kacchi", "Beef Curry", "Sold Out Soup"]
    assert mains_foods[2]["isAvailable"] is False
    assert [f["name"] for f in body["categories"][1]["foods"]] == ["Lassi"]
    assert [f["name"] for f in body["uncategorized"]] == ["Water"]
    assert "createdAt" not in mains_foods[0]


async def test_deleted_foods_are_not_on_the_menu(
    client: AsyncClient, manager: User, tea: Food
) -> None:
    await client.delete(f"/foods/{tea.id}", headers=auth_header(manager))

    body = (await client.get("/public/menu")).json()

    assert body["uncategorized"] == []


async def test_public_restaurant_info(client: AsyncClient, manager: User) -> None:
    await client.patch(
        "/restaurant",
        headers=auth_header(manager),
        json={"name": "Kacchi Bhai", "vatPercent": 5, "receiptFooter": "Thanks"},
    )

    body = (await client.get("/public/restaurant")).json()

    assert body["name"] == "Kacchi Bhai"
    assert body["vatPercent"] == 5
    assert body["acceptsQrOrders"] is True
    assert body["acceptsOnlineOrders"] is False
    assert "receiptFooter" not in body


# ordering from the table


async def test_table_from_qr_code(
    client: AsyncClient, session: AsyncSession, table: DiningTable
) -> None:
    closed = DiningTable(number="T8", seats=2, is_active=False)
    session.add(closed)
    await session.commit()

    found = await client.get(f"/public/tables/{table.qr_token}")
    assert found.json() == {"number": "T7", "location": "Rooftop"}
    assert (await client.get(f"/public/tables/{closed.qr_token}")).status_code == 404
    assert (await client.get("/public/tables/made-up")).status_code == 404


async def test_order_from_the_table(
    client: AsyncClient, manager: User, table: DiningTable, tea: Food
) -> None:
    await client.patch(
        "/restaurant", headers=auth_header(manager), json={"serviceChargePercent": 10}
    )
    body = order_body(tea, 2, customerName="Mina", notes="no sugar")
    body["items"][0]["unitPrice"] = 1

    response = await client.post(f"/public/tables/{table.qr_token}/orders", json=body)

    assert response.status_code == 201, response.text
    order = response.json()
    assert order["status"] == "pending"
    assert order["source"] == "qr"
    assert order["orderType"] == "dine_in"
    assert order["table"]["number"] == "T7"
    assert order["total"] == 44
    assert order["canCancel"] is True
    assert len(order["trackingCode"]) >= 16
    assert "waiter" not in order
    assert "payments" not in order

    staff_view = await client.get("/orders?source=qr", headers=auth_header(manager))
    assert staff_view.json()["total"] == 1
    assert staff_view.json()["items"][0]["createdBy"] is None


async def test_waiter_who_confirms_takes_the_order(
    client: AsyncClient,
    session: AsyncSession,
    make_user: UserFactory,
    table: DiningTable,
    tea: Food,
) -> None:
    waiter = await make_user(UserRole.WAITER)
    session.add(
        Employee(
            user_id=waiter.id,
            first_name="Wes",
            last_name="Lee",
            designation="Waiter",
            join_date=business_date(),
        )
    )
    await session.commit()
    placed = await client.post(f"/public/tables/{table.qr_token}/orders", json=order_body(tea))
    order_id = (await client.get("/orders", headers=auth_header(waiter))).json()["items"][0]["id"]
    assert placed.status_code == 201

    response = await client.post(
        f"/orders/{order_id}/status", headers=auth_header(waiter), json={"status": "confirmed"}
    )

    assert response.json()["waiter"]["fullName"] == "Wes Lee"


async def test_only_a_few_unconfirmed_orders_per_table(
    client: AsyncClient, table: DiningTable, tea: Food
) -> None:
    url = f"/public/tables/{table.qr_token}/orders"
    for _ in range(3):
        assert (await client.post(url, json=order_body(tea))).status_code == 201

    response = await client.post(url, json=order_body(tea))

    assert response.status_code == 409
    assert response.json()["code"] == "too_many_waiting_orders"


async def test_qr_ordering_can_be_switched_off(
    client: AsyncClient, manager: User, table: DiningTable, tea: Food
) -> None:
    await switch(client, manager, acceptsQrOrders=False)

    response = await client.post(f"/public/tables/{table.qr_token}/orders", json=order_body(tea))

    assert response.status_code == 409
    assert response.json()["code"] == "qr_orders_disabled"


async def test_new_qr_code_stops_the_old_one(
    client: AsyncClient, manager: User, table: DiningTable, tea: Food
) -> None:
    old_token = table.qr_token
    await client.post(f"/tables/{table.id}/qr-token", headers=auth_header(manager))

    response = await client.post(f"/public/tables/{old_token}/orders", json=order_body(tea))

    assert response.status_code == 404


# online takeaway


async def test_online_orders_are_off_by_default(client: AsyncClient, tea: Food) -> None:
    response = await client.post("/public/orders", json=order_body(tea, **ONLINE_CUSTOMER))

    assert response.status_code == 409
    assert response.json()["code"] == "online_orders_disabled"


async def test_online_takeaway(client: AsyncClient, manager: User, tea: Food) -> None:
    await switch(client, manager, acceptsOnlineOrders=True, serviceChargePercent=10)

    missing_phone = await client.post("/public/orders", json=order_body(tea, customerName="Mina"))
    response = await client.post("/public/orders", json=order_body(tea, 3, **ONLINE_CUSTOMER))

    assert missing_phone.status_code == 422
    assert response.status_code == 201
    order = response.json()
    assert order["orderType"] == "takeaway"
    assert order["source"] == "online"
    assert order["table"] is None
    assert order["serviceCharge"] == 0
    assert order["total"] == 60


async def test_online_orders_waiting_per_phone(
    client: AsyncClient, manager: User, tea: Food
) -> None:
    await switch(client, manager, acceptsOnlineOrders=True)
    for _ in range(3):
        await client.post("/public/orders", json=order_body(tea, **ONLINE_CUSTOMER))

    # same number written differently
    response = await client.post(
        "/public/orders",
        json=order_body(tea, customerName="Mina", customerPhone="017 1111-2222"),
    )

    assert response.json()["code"] == "too_many_waiting_orders"


# tracking and cancelling


async def test_track_any_order(client: AsyncClient, manager: User, tea: Food) -> None:
    placed = await client.post(
        "/orders", headers=auth_header(manager), json=order_body(tea, orderType="takeaway")
    )
    code = placed.json()["trackingCode"]
    await client.post(
        f"/orders/{placed.json()['id']}/status",
        headers=auth_header(manager),
        json={"status": "confirmed"},
    )

    response = await client.get(f"/public/orders/{code}")

    body = response.json()
    assert body["status"] == "confirmed"
    assert [step["toStatus"] for step in body["history"]] == ["pending", "confirmed"]
    assert body["canCancel"] is False
    assert (await client.get("/public/orders/not-a-real-code")).status_code == 404


async def test_customer_cancels_while_pending(
    client: AsyncClient, manager: User, table: DiningTable, tea: Food
) -> None:
    placed = await client.post(f"/public/tables/{table.qr_token}/orders", json=order_body(tea))
    code = placed.json()["trackingCode"]

    response = await client.post(f"/public/orders/{code}/cancel")

    body = response.json()
    assert body["status"] == "cancelled"
    assert body["cancelReason"] == "Cancelled by the customer"
    assert body["canCancel"] is False
    shown = await client.get("/orders?status=cancelled", headers=auth_header(manager))
    assert shown.json()["total"] == 1


async def test_customer_cant_cancel_after_confirmation(
    client: AsyncClient, manager: User, table: DiningTable, tea: Food
) -> None:
    placed = (
        await client.post(f"/public/tables/{table.qr_token}/orders", json=order_body(tea))
    ).json()
    order_id = (await client.get("/orders", headers=auth_header(manager))).json()["items"][0]["id"]
    await client.post(
        f"/orders/{order_id}/status", headers=auth_header(manager), json={"status": "confirmed"}
    )

    response = await client.post(f"/public/orders/{placed['trackingCode']}/cancel")

    assert response.status_code == 409
    assert response.json()["code"] == "cancel_not_allowed"


async def test_customer_cant_cancel_staff_or_paid_orders(
    client: AsyncClient, manager: User, table: DiningTable, tea: Food
) -> None:
    staff_order = (
        await client.post(
            "/orders", headers=auth_header(manager), json=order_body(tea, orderType="takeaway")
        )
    ).json()
    await switch(client, manager, acceptsOnlineOrders=True)
    online = (await client.post("/public/orders", json=order_body(tea, **ONLINE_CUSTOMER))).json()
    online_id = (await client.get("/orders?source=online", headers=auth_header(manager))).json()[
        "items"
    ][0]["id"]
    await client.post(
        f"/orders/{online_id}/payments", headers=auth_header(manager), json={"method": "card"}
    )

    for code in (staff_order["trackingCode"], online["trackingCode"]):
        response = await client.post(f"/public/orders/{code}/cancel")
        assert response.status_code == 409


# rate limits


async def test_login_is_rate_limited_per_account(
    client: AsyncClient, make_user: UserFactory
) -> None:
    await make_user(UserRole.WAITER, email="wes@example.com")
    wrong = {"email": "wes@example.com", "password": "not-the-password"}
    statuses = [(await client.post("/auth/login", json=wrong)).status_code for _ in range(6)]

    assert statuses == [401] * 5 + [429]
    blocked = await client.post("/auth/login", json=wrong)
    assert blocked.json()["code"] == "rate_limited"
    assert int(blocked.headers["retry-after"]) > 0
    # someone else logging in from the same office isn't blocked
    other = await client.post(
        "/auth/login", json={"email": "other@example.com", "password": "not-the-password"}
    )
    assert other.status_code == 401


async def test_placing_orders_is_rate_limited(
    client: AsyncClient, session: AsyncSession, tea: Food
) -> None:
    tables = [DiningTable(number=f"R{i}", seats=2) for i in range(4)]
    session.add_all(tables)
    await session.commit()

    statuses = [
        (await client.post(f"/public/tables/{t.qr_token}/orders", json=order_body(tea))).status_code
        for t in tables
        for _ in range(3)
    ]

    assert statuses.count(201) == 10
    assert statuses[-1] == 429


async def test_client_ip_behind_a_proxy(
    client: AsyncClient, tea: Food, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)

    async def menu_from(ip: str) -> int:
        # the first address is made up by the client, the proxy added the last one
        headers = {"X-Forwarded-For": f"6.6.6.6, {ip}"}
        return (await client.get("/public/menu", headers=headers)).status_code

    first = [await menu_from("203.0.113.1") for _ in range(121)]
    second = await menu_from("203.0.113.2")

    assert first[-1] == 429
    assert second == 200


async def test_client_ip_from_a_header_the_proxy_sets(
    client: AsyncClient, tea: Food, monkeypatch: pytest.MonkeyPatch
) -> None:
    # like fastapi cloud: cloudflare sets CF-Connecting-IP, X-Forwarded-For can be made up
    monkeypatch.setattr(settings, "client_ip_header", "cf-connecting-ip")
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)

    async def login_from(ip: str, fake: str) -> int:
        headers = {"CF-Connecting-IP": ip, "X-Forwarded-For": f"{fake}, 10.0.0.1"}
        body = {"email": "nobody@example.com", "password": "wrong"}
        return (await client.post("/auth/login", headers=headers, json=body)).status_code

    # a new made up address every time doesn't get around the limit
    attempts = [await login_from("203.0.113.7", f"6.6.6.{n}") for n in range(6)]
    assert attempts[:5] == [401] * 5
    assert attempts[5] == 429
    assert await login_from("203.0.113.8", "6.6.6.6") == 401
