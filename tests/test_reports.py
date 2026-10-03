import csv
import io
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from itertools import count

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutils import business_date, restaurant_tz, utcnow
from app.models import (
    Category,
    DiningTable,
    Employee,
    Expense,
    Food,
    Order,
    OrderItem,
    OrderStatus,
    OrderType,
    User,
    UserRole,
)
from tests.conftest import UserFactory, auth_header

pytestmark = pytest.mark.anyio

_numbers = count(1)


def at(day: date, hour: int = 12) -> datetime:
    """A moment on a local business day."""
    return datetime.combine(day, time(hour), tzinfo=restaurant_tz())


@pytest.fixture
async def manager(make_user: UserFactory) -> User:
    return await make_user(UserRole.MANAGER)


@pytest.fixture
async def foods(session: AsyncSession) -> dict[str, Food]:
    mains = Category(name="Mains")
    foods = {
        "biryani": Food(name="Kacchi Biryani", price=Decimal("400"), category=mains),
        "tea": Food(name="Tea", price=Decimal("20")),
        "lassi": Food(name="Lassi", price=Decimal("90")),
    }
    session.add_all(foods.values())
    await session.commit()
    return foods


async def add_order(
    session: AsyncSession,
    lines: list[tuple[Food, int]],
    status: OrderStatus = OrderStatus.PAID,
    when: datetime | None = None,
    waiter_id: int | None = None,
    table_id: int | None = None,
) -> Order:
    """Inserts an order straight into the database, skipping the status flow."""
    when = when or utcnow()
    items = [
        OrderItem(
            food_id=food.id,
            food_name=food.name,
            unit_price=food.price,
            final_unit_price=food.price,
            quantity=quantity,
            line_total=food.price * quantity,
        )
        for food, quantity in lines
    ]
    total = sum((item.line_total for item in items), Decimal(0))
    order = Order(
        order_number=f"T-{next(_numbers)}",
        order_type=OrderType.DINE_IN if table_id else OrderType.TAKEAWAY,
        table_id=table_id,
        status=status,
        waiter_id=waiter_id,
        items=items,
        subtotal=total,
        total=total,
        created_at=when,
        closed_at=when if status in (OrderStatus.PAID, OrderStatus.CANCELLED) else None,
    )
    session.add(order)
    await session.commit()
    return order


# top foods


async def test_top_foods_only_counts_paid_orders(
    client: AsyncClient, session: AsyncSession, manager: User, foods: dict[str, Food]
) -> None:
    await add_order(session, [(foods["tea"], 3), (foods["biryani"], 1)])
    await add_order(session, [(foods["tea"], 2)])
    await add_order(session, [(foods["biryani"], 5)], status=OrderStatus.CANCELLED)
    await add_order(session, [(foods["lassi"], 9)], status=OrderStatus.SERVED)

    response = await client.get("/reports/top-foods", headers=auth_header(manager))

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [(i["name"], i["quantity"], i["orders"]) for i in items] == [
        ("Tea", 5, 2),
        ("Kacchi Biryani", 1, 1),
    ]
    assert items[0]["revenue"] == 100
    assert items[1]["category"] == "Mains"


async def test_top_foods_range_and_category(
    client: AsyncClient, session: AsyncSession, manager: User, foods: dict[str, Food]
) -> None:
    today = business_date()
    last_year = today.replace(year=today.year - 1)
    await add_order(session, [(foods["tea"], 1)], when=at(last_year))
    await add_order(session, [(foods["biryani"], 1), (foods["tea"], 4)])
    headers = auth_header(manager)

    old = (
        await client.get(
            f"/reports/top-foods?dateFrom={last_year}&dateTo={last_year}", headers=headers
        )
    ).json()
    assert [(i["name"], i["quantity"]) for i in old["items"]] == [("Tea", 1)]
    assert old["dateFrom"] == old["dateTo"] == last_year.isoformat()

    mains = foods["biryani"].category_id
    only_mains = (
        await client.get(f"/reports/top-foods?categoryId={mains}", headers=headers)
    ).json()
    assert [i["name"] for i in only_mains["items"]] == ["Kacchi Biryani"]


@pytest.mark.parametrize(
    "query",
    [
        "dateFrom=2026-05-02&dateTo=2026-05-01",
        "dateFrom=2000-01-01&dateTo=2026-01-01",
        "limit=0",
    ],
)
async def test_invalid_ranges(client: AsyncClient, manager: User, query: str) -> None:
    response = await client.get(f"/reports/top-foods?{query}", headers=auth_header(manager))

    assert response.status_code == 422


async def test_reports_are_for_managers(client: AsyncClient, make_user: UserFactory) -> None:
    for role in (UserRole.WAITER, UserRole.CHEF, UserRole.CASHIER):
        user = await make_user(role)
        response = await client.get("/reports/top-foods", headers=auth_header(user))
        assert response.status_code == 403


# dashboard


async def test_dashboard(
    client: AsyncClient, session: AsyncSession, manager: User, foods: dict[str, Food]
) -> None:
    today = business_date()
    session.add_all(
        [
            DiningTable(number="T1", seats=4),
            DiningTable(number="T2", seats=2),
            Expense(title="Gas", category="utilities", amount=50, expense_date=today),
            Expense(
                title="Rent",
                category="rent",
                amount=1000,
                expense_date=today.replace(month=1, day=1),
            ),
        ]
    )
    await session.commit()
    table = await session.scalar(select(DiningTable).where(DiningTable.number == "T1"))
    await add_order(session, [(foods["biryani"], 2)])
    await add_order(session, [(foods["tea"], 5)])
    await add_order(session, [(foods["tea"], 1)], status=OrderStatus.CANCELLED)
    await add_order(session, [(foods["lassi"], 1)], status=OrderStatus.PREPARING, table_id=table.id)
    await add_order(session, [(foods["tea"], 1)], when=at(today.replace(year=today.year - 1)))

    response = await client.get("/dashboard", headers=auth_header(manager))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["businessDate"] == today.isoformat()
    assert body["today"] == {
        "orders": 2,
        "sales": 900,
        "expenses": 50,
        "profit": 850,
        "averageOrder": 450,
    }
    assert body["allTime"]["orders"] == 3
    assert body["allTime"]["sales"] == 920
    assert body["allTime"]["expenses"] == 1050
    assert body["ordersToday"] == 3
    assert body["cancelledToday"] == 1
    assert body["openOrders"]["preparing"] == 1
    assert body["openOrders"]["total"] == 1
    assert body["tables"] == {"total": 2, "occupied": 1, "free": 1}
    assert body["menu"] == {"foods": 3, "available": 3}
    assert len(body["recentOrders"]) == 5
    assert body["recentOrders"][0]["table"]["number"] == "T1"
    assert body["topFoodsThisMonth"][0]["name"] == "Tea"


async def test_dashboard_when_empty(client: AsyncClient, make_user: UserFactory) -> None:
    cashier = await make_user(UserRole.CASHIER)

    body = (await client.get("/dashboard", headers=auth_header(cashier))).json()

    assert body["today"]["averageOrder"] == 0
    assert body["recentOrders"] == []
    assert body["openOrders"]["total"] == 0


async def test_dashboard_today_follows_restaurant_time(
    client: AsyncClient, session: AsyncSession, manager: User, foods: dict[str, Food]
) -> None:
    today = business_date()
    # 00:30 local is still the previous day in UTC, it has to count as today
    await add_order(session, [(foods["tea"], 1)], when=at(today, hour=0) + timedelta(minutes=30))
    # 23:30 local yesterday is the same UTC date as above in Dhaka, it must not count
    await add_order(session, [(foods["tea"], 2)], when=at(today, hour=0) - timedelta(minutes=30))

    body = (await client.get("/dashboard", headers=auth_header(manager))).json()

    assert body["today"]["orders"] == 1


async def test_dashboard_with_the_real_order_flow(
    client: AsyncClient, manager: User, foods: dict[str, Food]
) -> None:
    headers = auth_header(manager)
    created = await client.post(
        "/orders",
        headers=headers,
        json={"orderType": "takeaway", "items": [{"foodId": foods["lassi"].id, "quantity": 2}]},
    )
    order_id = created.json()["id"]
    for status in ("confirmed", "preparing", "ready", "served"):
        response = await client.post(
            f"/orders/{order_id}/status", headers=headers, json={"status": status}
        )
        assert response.status_code == 200, response.text
    paid = await client.post(
        f"/orders/{order_id}/payments", headers=headers, json={"method": "cash"}
    )
    assert paid.json()["status"] == "paid"

    body = (await client.get("/dashboard", headers=headers)).json()

    assert body["today"]["orders"] == 1
    assert body["today"]["sales"] == 180
    assert body["openOrders"]["total"] == 0


# sales


async def test_daily_sales_fill_the_gaps(
    client: AsyncClient, session: AsyncSession, manager: User, foods: dict[str, Food]
) -> None:
    first = date(2026, 3, 1)
    await add_order(session, [(foods["biryani"], 1)], when=at(first))
    await add_order(session, [(foods["tea"], 5)], when=at(first, hour=23))
    await add_order(session, [(foods["lassi"], 2)], when=at(date(2026, 3, 3)))
    await add_order(
        session, [(foods["lassi"], 2)], when=at(date(2026, 3, 3)), status=OrderStatus.CANCELLED
    )
    session.add(Expense(title="Fish", category="ingredients", amount=700, expense_date=first))
    await session.commit()

    response = await client.get(
        "/reports/sales?dateFrom=2026-03-01&dateTo=2026-03-04", headers=auth_header(manager)
    )

    assert response.status_code == 200, response.text
    body = response.json()
    rows = [(r["periodStart"], r["orders"], r["sales"], r["profit"]) for r in body["rows"]]
    assert rows == [
        ("2026-03-01", 2, 500, -200),
        ("2026-03-02", 0, 0, 0),
        ("2026-03-03", 1, 180, 180),
        ("2026-03-04", 0, 0, 0),
    ]
    assert body["totals"]["orders"] == 3
    assert body["totals"]["sales"] == 680
    assert body["totals"]["expenses"] == 700
    assert body["totals"]["averageOrder"] == 226.67


async def test_sales_by_week_and_month(
    client: AsyncClient, session: AsyncSession, manager: User, foods: dict[str, Food]
) -> None:
    # 2026-03-01 is a sunday, so it's the last day of its week
    await add_order(session, [(foods["tea"], 1)], when=at(date(2026, 3, 1)))
    await add_order(session, [(foods["tea"], 2)], when=at(date(2026, 3, 2)))
    await add_order(session, [(foods["tea"], 4)], when=at(date(2026, 4, 30)))
    headers = auth_header(manager)

    weeks = (
        await client.get(
            "/reports/sales?dateFrom=2026-03-01&dateTo=2026-03-10&groupBy=week", headers=headers
        )
    ).json()["rows"]
    assert [(r["periodStart"], r["periodEnd"], r["sales"]) for r in weeks] == [
        ("2026-03-01", "2026-03-01", 20),
        ("2026-03-02", "2026-03-08", 40),
        ("2026-03-09", "2026-03-10", 0),
    ]

    months = (
        await client.get(
            "/reports/sales?dateFrom=2026-01-15&dateTo=2026-05-31&groupBy=month", headers=headers
        )
    ).json()["rows"]
    assert [(r["periodStart"], r["sales"]) for r in months] == [
        ("2026-01-15", 0),
        ("2026-02-01", 0),
        ("2026-03-01", 60),
        ("2026-04-01", 80),
        ("2026-05-01", 0),
    ]


async def test_late_night_sales_count_on_the_local_day(
    client: AsyncClient, session: AsyncSession, manager: User, foods: dict[str, Food]
) -> None:
    # 01:00 in Dhaka on the 2nd is still the 1st in UTC
    await add_order(session, [(foods["tea"], 1)], when=at(date(2026, 3, 2), hour=1))

    rows = (
        await client.get(
            "/reports/sales?dateFrom=2026-03-01&dateTo=2026-03-02", headers=auth_header(manager)
        )
    ).json()["rows"]

    assert [r["orders"] for r in rows] == [0, 1]


async def test_too_many_days(client: AsyncClient, manager: User) -> None:
    response = await client.get(
        "/reports/sales?dateFrom=2024-01-01&dateTo=2026-01-01", headers=auth_header(manager)
    )

    assert response.status_code == 422
    yearly = await client.get(
        "/reports/sales?dateFrom=2024-01-01&dateTo=2026-01-01&groupBy=year",
        headers=auth_header(manager),
    )
    assert [r["periodStart"] for r in yearly.json()["rows"]] == [
        "2024-01-01",
        "2025-01-01",
        "2026-01-01",
    ]


# expenses


async def test_expenses_by_category(
    client: AsyncClient, session: AsyncSession, manager: User
) -> None:
    day = date(2026, 3, 10)
    session.add_all(
        [
            Expense(title="Rice", category="ingredients", amount=300, expense_date=day),
            Expense(title="Fish", category="ingredients", amount=450, expense_date=day),
            Expense(title="Power", category="utilities", amount=250, expense_date=day),
            Expense(title="Rent", category="rent", amount=9000, expense_date=date(2026, 2, 1)),
        ]
    )
    await session.commit()

    response = await client.get(
        "/reports/expenses?dateFrom=2026-03-01&dateTo=2026-03-31", headers=auth_header(manager)
    )

    body = response.json()
    assert body["total"] == 1000
    assert body["categories"] == [
        {"category": "ingredients", "count": 2, "amount": 750, "share": 75.0},
        {"category": "utilities", "count": 1, "amount": 250, "share": 25.0},
    ]


# staff


def employee(first_name: str, **kwargs) -> Employee:
    return Employee(
        first_name=first_name,
        last_name="Test",
        designation="Waiter",
        join_date=date(2025, 1, 1),
        **kwargs,
    )


async def test_staff_performance(
    client: AsyncClient, session: AsyncSession, manager: User, foods: dict[str, Food]
) -> None:
    rafi, nila, tanim, gone = (
        employee("Rafi"),
        employee("Nila"),
        employee("Tanim"),
        employee("Gone", is_active=False),
    )
    session.add_all([rafi, nila, tanim, gone, employee("Left", is_active=False)])
    await session.commit()
    day = at(date(2026, 3, 5))
    await add_order(
        session, [(foods["biryani"], 2), (foods["tea"], 2)], when=day, waiter_id=nila.id
    )
    await add_order(session, [(foods["tea"], 1)], when=day, waiter_id=rafi.id)
    await add_order(
        session, [(foods["tea"], 3)], when=day, waiter_id=rafi.id, status=OrderStatus.CANCELLED
    )
    await add_order(session, [(foods["lassi"], 1)], when=day, waiter_id=gone.id)
    # outside the range
    await add_order(session, [(foods["biryani"], 9)], when=at(date(2026, 4, 1)), waiter_id=rafi.id)

    response = await client.get(
        "/reports/staff?dateFrom=2026-03-01&dateTo=2026-03-31", headers=auth_header(manager)
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["totalSales"] == 950
    rows = {r["employee"]["fullName"]: r for r in body["rows"]}
    # people who left only show up when they sold something
    assert list(rows) == ["Nila Test", "Gone Test", "Rafi Test", "Tanim Test"]
    assert rows["Nila Test"] | {"employee": None} == {
        "employee": None,
        "orders": 1,
        "itemsSold": 4,
        "sales": 840,
        "averageOrder": 840,
        "cancelled": 0,
        "share": 88.4,
    }
    assert rows["Rafi Test"]["cancelled"] == 1
    assert rows["Rafi Test"]["itemsSold"] == 1
    assert rows["Gone Test"]["employee"]["isActive"] is False
    assert rows["Tanim Test"]["sales"] == 0


# csv


def read_csv(response) -> list[list[str]]:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    text = response.content.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text)))


async def test_sales_csv(
    client: AsyncClient, session: AsyncSession, manager: User, foods: dict[str, Food]
) -> None:
    await add_order(session, [(foods["biryani"], 1)], when=at(date(2026, 3, 1)))

    response = await client.get(
        "/reports/sales.csv?dateFrom=2026-03-01&dateTo=2026-03-02", headers=auth_header(manager)
    )

    assert response.content.startswith("﻿".encode())
    assert (
        'filename="sales-2026-03-01-to-2026-03-02.csv"' in response.headers["content-disposition"]
    )
    rows = read_csv(response)
    assert rows[0][:4] == ["From", "To", "Orders", "Sales"]
    assert rows[1][:4] == ["2026-03-01", "2026-03-01", "1", "400.00"]
    assert len(rows) == 3


async def test_orders_csv(
    client: AsyncClient, session: AsyncSession, manager: User, foods: dict[str, Food]
) -> None:
    waiter = employee("Rafi")
    session.add(waiter)
    await session.commit()
    day = date(2026, 3, 1)
    await add_order(session, [(foods["tea"], 3), (foods["lassi"], 1)], when=at(day, hour=21))
    cancelled = await add_order(
        session,
        [(foods["tea"], 1)],
        when=at(day),
        status=OrderStatus.CANCELLED,
        waiter_id=waiter.id,
    )
    cancelled.cancel_reason = "customer left"
    await add_order(session, [(foods["tea"], 1)], when=at(day), status=OrderStatus.SERVED)
    await session.commit()

    rows = read_csv(
        await client.get(
            "/reports/orders.csv?dateFrom=2026-03-01&dateTo=2026-03-01",
            headers=auth_header(manager),
        )
    )

    assert len(rows) == 3
    first, second = rows[1], rows[2]
    assert second[1] == "2026-03-01 21:00"
    assert second[2] == "paid"
    assert second[6] == "4"
    assert first[5] == "Rafi Test"
    assert first[10] == "customer left"


async def test_csv_cells_cant_be_formulas(
    client: AsyncClient, session: AsyncSession, manager: User
) -> None:
    food = Food(name="=1+1", price=Decimal("10"))
    session.add(food)
    await session.commit()
    await add_order(session, [(food, 1)])

    rows = read_csv(await client.get("/reports/top-foods.csv", headers=auth_header(manager)))

    assert rows[1][0] == "'=1+1"


@pytest.mark.parametrize("report", ["sales", "top-foods", "expenses", "staff", "orders"])
async def test_every_csv_works_when_empty(client: AsyncClient, manager: User, report: str) -> None:
    rows = read_csv(await client.get(f"/reports/{report}.csv", headers=auth_header(manager)))

    assert rows[0]
