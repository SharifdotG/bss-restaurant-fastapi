from collections import defaultdict
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.core.timeutils import business_date, utcnow
from app.models import Food, Order, OrderStatus, Payment, Reservation, User
from app.services.demo import seed_demo

pytestmark = pytest.mark.anyio

PASSWORD = "demo-pass1"


@pytest.fixture
async def demo(session: AsyncSession):
    return await seed_demo(session, password=PASSWORD, days=7, seed=42)


async def login(client: AsyncClient, email: str) -> dict:
    response = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


async def test_staff_can_log_in_and_see_it(client: AsyncClient, demo) -> None:
    assert [role for _, role in demo.users] == ["manager", "cashier", "waiter", "waiter", "chef"]
    headers = await login(client, "manager@example.com")

    dashboard = (await client.get("/dashboard", headers=headers)).json()
    assert dashboard["allTime"]["orders"] > 0
    assert dashboard["reservations"]["requests"] == 2
    assert dashboard["openOrders"]["total"] == 6
    assert dashboard["menu"]["foods"] == 26

    menu = (await client.get("/public/menu")).json()
    assert menu["restaurant"]["name"] == "Shorshe Kitchen"
    assert [c["name"] for c in menu["categories"]][0] == "Starters"

    tables = (await client.get("/tables", headers=headers)).json()
    assert tables["total"] == 10
    assert all(len(t["employees"]) == 1 for t in tables["items"])


async def test_the_money_adds_up(session: AsyncSession, demo) -> None:
    paid = await session.scalar(
        select(func.sum(Order.total)).where(Order.status == OrderStatus.PAID)
    )
    payments = await session.scalar(select(func.sum(Payment.amount)))
    assert paid == payments > 0

    unbalanced = await session.scalar(
        select(func.count()).where(
            Order.status == OrderStatus.PAID, Order.amount_paid != Order.total
        )
    )
    assert unbalanced == 0
    # dine in orders carry the service charge, everything carries vat
    order = await session.scalar(select(Order).where(Order.service_charge > 0).limit(1))
    assert order.service_charge_rate == Decimal(5)
    assert order.vat_rate == Decimal("7.5")


async def test_order_numbers_follow_the_day_they_were_placed(
    session: AsyncSession, client: AsyncClient, demo
) -> None:
    rows = await session.execute(select(Order.order_number, Order.created_at))
    by_day = defaultdict(list)
    for number, created_at in rows:
        prefix, counter = number.split("-")
        assert prefix == f"{business_date(created_at):%y%m%d}"
        by_day[prefix].append(int(counter))
    for counters in by_day.values():
        assert sorted(counters) == list(range(1, len(counters) + 1))

    # the next real order continues today's numbering
    headers = await login(client, "waiter@example.com")
    food = await session.scalar(select(Food.id).limit(1))
    response = await client.post(
        "/orders",
        headers=headers,
        json={"orderType": "takeaway", "items": [{"foodId": food, "quantity": 1}]},
    )
    today = f"{business_date():%y%m%d}"
    assert response.json()["orderNumber"] == f"{today}-{len(by_day[today]) + 1:04d}"


async def test_nothing_happens_in_the_future(session: AsyncSession, demo) -> None:
    now = utcnow()
    assert await session.scalar(select(func.max(Order.created_at))) <= now
    assert await session.scalar(select(func.max(Order.closed_at))) <= now
    assert await session.scalar(select(func.max(Payment.created_at))) <= now
    upcoming = await session.scalar(
        select(func.count()).where(Reservation.starts_at > now, Reservation.status == "confirmed")
    )
    assert upcoming == 9


async def test_counts_match_the_summary(session: AsyncSession, demo) -> None:
    totals = (await session.execute(select(Order.order_number, Order.total))).all()
    assert len(totals) == demo.orders
    assert await session.scalar(select(func.count()).select_from(User)) == 5


async def test_only_into_an_empty_database(session: AsyncSession, demo) -> None:
    with pytest.raises(ConflictError):
        await seed_demo(session, password=PASSWORD, days=1)
