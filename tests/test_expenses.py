from datetime import timedelta

import pytest
from httpx import AsyncClient

from app.core.timeutils import business_date
from app.models import User, UserRole
from tests.conftest import UserFactory, auth_header
from tests.test_uploads import make_image

pytestmark = pytest.mark.anyio


@pytest.fixture
async def cashier(make_user: UserFactory) -> User:
    return await make_user(UserRole.CASHIER, first_name="Cara", last_name="Cash")


async def add_expense(client: AsyncClient, user: User, **overrides) -> dict:
    payload = {"title": "Vegetables", "category": "ingredients", "amount": 1250.5} | overrides
    response = await client.post("/expenses", headers=auth_header(user), json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_expense(client: AsyncClient, cashier: User) -> None:
    expense = await add_expense(client, cashier, paidTo="Karwan Bazar")

    assert expense["amount"] == 1250.5
    assert expense["expenseDate"] == business_date().isoformat()
    assert expense["createdBy"]["fullName"] == "Cara Cash"
    assert expense["receiptUrl"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"amount": 0},
        {"amount": -10},
        {"category": "fun"},
        {"expenseDate": (business_date() + timedelta(days=1)).isoformat()},
    ],
)
async def test_invalid_expenses(client: AsyncClient, cashier: User, payload: dict) -> None:
    body = {"title": "X", "category": "other", "amount": 10} | payload

    response = await client.post("/expenses", headers=auth_header(cashier), json=body)

    assert response.status_code == 422


async def test_waiters_and_chefs_have_no_access(
    client: AsyncClient, make_user: UserFactory
) -> None:
    for role in (UserRole.WAITER, UserRole.CHEF):
        user = await make_user(role)
        assert (await client.get("/expenses", headers=auth_header(user))).status_code == 403


async def test_only_managers_delete(
    client: AsyncClient, make_user: UserFactory, cashier: User
) -> None:
    manager = await make_user(UserRole.MANAGER)
    expense = await add_expense(client, cashier)
    url = f"/expenses/{expense['id']}"

    assert (await client.delete(url, headers=auth_header(cashier))).status_code == 403
    assert (await client.delete(url, headers=auth_header(manager))).status_code == 204
    assert (await client.get(url, headers=auth_header(manager))).status_code == 404


async def test_list_filters(client: AsyncClient, cashier: User) -> None:
    today = business_date()
    last_week = (today - timedelta(days=7)).isoformat()
    await add_expense(client, cashier, title="Rice", amount=3000)
    await add_expense(client, cashier, title="Electricity", category="utilities", amount=8000)
    await add_expense(client, cashier, title="Old rent", category="rent", expenseDate=last_week)
    headers = auth_header(cashier)

    newest_first = (await client.get("/expenses", headers=headers)).json()
    assert newest_first["items"][-1]["title"] == "Old rent"

    bills = (await client.get("/expenses?category=utilities&category=rent", headers=headers)).json()
    assert {e["title"] for e in bills["items"]} == {"Electricity", "Old rent"}

    this_week = (
        await client.get(f"/expenses?dateFrom={today.isoformat()}", headers=headers)
    ).json()
    assert this_week["total"] == 2

    big = (await client.get("/expenses?minAmount=5000", headers=headers)).json()
    assert [e["title"] for e in big["items"]] == ["Electricity"]

    by_amount = (await client.get("/expenses?sort=-amount", headers=headers)).json()
    assert by_amount["items"][0]["title"] == "Electricity"

    found = (await client.get("/expenses?search=elec", headers=headers)).json()
    assert found["total"] == 1


async def test_update_and_receipt(client: AsyncClient, cashier: User) -> None:
    headers = auth_header(cashier)
    expense = await add_expense(client, cashier)
    upload = await client.post(
        "/uploads/images",
        headers=headers,
        data={"folder": "receipts"},
        files={"file": ("r.png", make_image(), "image/png")},
    )

    response = await client.patch(
        f"/expenses/{expense['id']}",
        headers=headers,
        json={"amount": 1300, "receiptKey": upload.json()["key"], "notes": None},
    )

    body = response.json()
    assert body["amount"] == 1300
    assert body["receiptUrl"].endswith(".webp")
    assert body["title"] == "Vegetables"
