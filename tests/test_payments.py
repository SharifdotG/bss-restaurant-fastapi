from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DiningTable, Food, User, UserRole
from tests.conftest import UserFactory, auth_header

pytestmark = pytest.mark.anyio


@pytest.fixture
async def manager(make_user: UserFactory) -> User:
    return await make_user(UserRole.MANAGER)


@pytest.fixture
async def cashier(make_user: UserFactory) -> User:
    return await make_user(UserRole.CASHIER)


@pytest.fixture
async def menu(session: AsyncSession) -> dict[str, Food]:
    foods = {
        "kacchi": Food(
            name="Kacchi Biryani", price=Decimal("420"), discount_type="flat", discount_value=20
        ),
        "borhani": Food(name="Borhani", price=Decimal("80")),
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


async def set_rates(client: AsyncClient, manager: User, vat: float, service: float) -> None:
    response = await client.patch(
        "/restaurant",
        headers=auth_header(manager),
        json={"vatPercent": vat, "serviceChargePercent": service},
    )
    assert response.status_code == 200, response.text


async def place(client: AsyncClient, user: User, items: list[tuple[Food, int]], **extra) -> dict:
    response = await client.post(
        "/orders",
        headers=auth_header(user),
        json={"items": [{"foodId": f.id, "quantity": q} for f, q in items], **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def serve(client: AsyncClient, user: User, order: dict) -> dict:
    for status in ("confirmed", "preparing", "ready", "served"):
        response = await client.post(
            f"/orders/{order['id']}/status", headers=auth_header(user), json={"status": status}
        )
        assert response.status_code == 200, response.text
    return response.json()


async def pay(client: AsyncClient, user: User, order: dict, **body):
    return await client.post(
        f"/orders/{order['id']}/payments", headers=auth_header(user), json=body
    )


async def refund(client: AsyncClient, user: User, order: dict, **body):
    body.setdefault("reason", "customer complaint")
    return await client.post(f"/orders/{order['id']}/refunds", headers=auth_header(user), json=body)


# restaurant settings


async def test_restaurant_starts_with_defaults(client: AsyncClient, make_user: UserFactory) -> None:
    waiter = await make_user(UserRole.WAITER)

    response = await client.get("/restaurant", headers=auth_header(waiter))

    assert response.status_code == 200
    assert response.json()["currency"] == "BDT"
    assert response.json()["vatPercent"] == 0


async def test_manager_updates_the_restaurant(client: AsyncClient, manager: User) -> None:
    headers = auth_header(manager)
    await client.patch(
        "/restaurant",
        headers=headers,
        json={"name": "Kacchi Bhai", "address": "Dhanmondi", "vatPercent": 7.5},
    )

    response = await client.patch("/restaurant", headers=headers, json={"address": None})

    body = response.json()
    assert body["name"] == "Kacchi Bhai"
    assert body["vatPercent"] == 7.5
    assert body["address"] is None


@pytest.mark.parametrize(
    "payload",
    [{"vatPercent": 101}, {"serviceChargePercent": -1}, {"currency": "taka"}, {"name": ""}],
)
async def test_invalid_restaurant_settings(
    client: AsyncClient, manager: User, payload: dict
) -> None:
    response = await client.patch("/restaurant", headers=auth_header(manager), json=payload)

    assert response.status_code == 422


async def test_only_managers_change_the_restaurant(client: AsyncClient, cashier: User) -> None:
    response = await client.patch("/restaurant", headers=auth_header(cashier), json={"name": "x"})

    assert response.status_code == 403


# bill


async def test_dine_in_bill_with_service_charge_and_vat(
    client: AsyncClient, manager: User, menu: dict[str, Food], table: DiningTable
) -> None:
    await set_rates(client, manager, vat=5, service=10)

    order = await place(
        client, manager, [(menu["kacchi"], 2), (menu["borhani"], 3)], tableId=table.id
    )

    # 2 x 400 + 3 x 80 = 1040, service 104, vat 5% of 1144 = 57.20
    assert order["subtotal"] == 1080
    assert order["discountTotal"] == 40
    assert order["serviceCharge"] == 104
    assert order["vat"] == 57.2
    assert order["total"] == 1201.2
    assert order["balanceDue"] == 1201.2
    assert order["amountPaid"] == 0


async def test_takeaway_has_no_service_charge(
    client: AsyncClient, manager: User, menu: dict[str, Food]
) -> None:
    await set_rates(client, manager, vat=5, service=10)

    order = await place(client, manager, [(menu["borhani"], 1)], orderType="takeaway")

    assert order["serviceChargeRate"] == 0
    assert order["serviceCharge"] == 0
    assert order["total"] == 84


async def test_rates_stay_with_the_order(
    client: AsyncClient, manager: User, menu: dict[str, Food], table: DiningTable
) -> None:
    await set_rates(client, manager, vat=10, service=0)
    order = await place(client, manager, [(menu["borhani"], 1)], tableId=table.id)
    await set_rates(client, manager, vat=15, service=0)

    response = await client.post(
        f"/orders/{order['id']}/items",
        headers=auth_header(manager),
        json={"items": [{"foodId": menu["borhani"].id, "quantity": 1}]},
    )

    assert response.json()["vatRate"] == 10
    assert response.json()["vat"] == 16


# payments


async def test_split_bill_settles_a_served_order(
    client: AsyncClient,
    manager: User,
    cashier: User,
    menu: dict[str, Food],
    table: DiningTable,
) -> None:
    order = await place(client, manager, [(menu["kacchi"], 2)], tableId=table.id)
    await serve(client, manager, order)

    first = await pay(client, cashier, order, method="card", amount=300, reference="4242")
    assert first.status_code == 201
    assert first.json()["status"] == "served"
    assert first.json()["balanceDue"] == 500

    second = await pay(client, cashier, order, method="mobile", reference="TRX123")

    body = second.json()
    assert body["status"] == "paid"
    assert body["closedAt"] is not None
    assert body["amountPaid"] == 800
    assert body["balanceDue"] == 0
    assert [(p["method"], p["amount"]) for p in body["payments"]] == [
        ("card", 300),
        ("mobile", 500),
    ]
    assert body["history"][-1]["toStatus"] == "paid"
    assert body["history"][-1]["changedBy"]["id"] == cashier.id


async def test_cash_change(
    client: AsyncClient, manager: User, cashier: User, menu: dict[str, Food]
) -> None:
    order = await place(client, manager, [(menu["borhani"], 2)], orderType="takeaway")

    response = await pay(client, cashier, order, method="cash", tendered=500)

    payment = response.json()["payments"][0]
    assert payment["amount"] == 160
    assert payment["tendered"] == 500
    assert payment["change"] == 340


async def test_paid_up_front_closes_when_served(
    client: AsyncClient, manager: User, cashier: User, menu: dict[str, Food]
) -> None:
    order = await place(client, manager, [(menu["borhani"], 1)], orderType="takeaway")
    paid = await pay(client, cashier, order, method="card")
    assert paid.json()["status"] == "pending"
    assert paid.json()["balanceDue"] == 0

    served = await serve(client, manager, order)

    assert served["status"] == "paid"
    assert [e["toStatus"] for e in served["history"]][-2:] == ["served", "paid"]


async def test_paid_cant_be_set_by_hand(
    client: AsyncClient, manager: User, menu: dict[str, Food]
) -> None:
    order = await place(client, manager, [(menu["borhani"], 1)], orderType="takeaway")
    served = await serve(client, manager, order)
    assert served["nextStatuses"] == []

    response = await client.post(
        f"/orders/{order['id']}/status", headers=auth_header(manager), json={"status": "paid"}
    )

    assert response.status_code == 409
    assert response.json()["code"] == "payment_required"
    assert response.json()["balanceDue"] == 80


async def test_payment_mistakes(
    client: AsyncClient, manager: User, cashier: User, menu: dict[str, Food]
) -> None:
    order = await place(client, manager, [(menu["borhani"], 1)], orderType="takeaway")

    too_much = await pay(client, cashier, order, method="card", amount=100)
    assert too_much.status_code == 409
    assert too_much.json()["code"] == "overpayment"
    assert too_much.json()["balanceDue"] == 80

    short = await pay(client, cashier, order, method="cash", amount=80, tendered=50)
    assert short.status_code == 422
    no_reference = await pay(client, cashier, order, method="mobile")
    assert no_reference.status_code == 422
    card_change = await pay(client, cashier, order, method="card", tendered=100)
    assert card_change.status_code == 422

    await pay(client, cashier, order, method="card")
    again = await pay(client, cashier, order, method="card")
    assert again.json()["code"] == "nothing_to_pay"


async def test_waiters_dont_take_money(
    client: AsyncClient, make_user: UserFactory, manager: User, menu: dict[str, Food]
) -> None:
    waiter = await make_user(UserRole.WAITER)
    order = await place(client, manager, [(menu["borhani"], 1)], orderType="takeaway")

    response = await pay(client, waiter, order, method="cash")

    assert response.status_code == 403


async def test_no_payments_on_closed_orders(
    client: AsyncClient, manager: User, cashier: User, menu: dict[str, Food]
) -> None:
    order = await place(client, manager, [(menu["borhani"], 1)], orderType="takeaway")
    await client.post(
        f"/orders/{order['id']}/status",
        headers=auth_header(manager),
        json={"status": "cancelled", "note": "wrong order"},
    )

    response = await pay(client, cashier, order, method="cash")

    assert response.status_code == 409
    assert response.json()["code"] == "order_closed"


# refunds


async def test_refund_after_paying(
    client: AsyncClient, manager: User, cashier: User, menu: dict[str, Food]
) -> None:
    order = await place(client, manager, [(menu["kacchi"], 1)], orderType="takeaway")
    await serve(client, manager, order)
    await pay(client, cashier, order, method="cash")

    by_cashier = await refund(client, cashier, order, method="cash", amount=50)
    assert by_cashier.status_code == 403
    too_much = await refund(client, manager, order, method="cash", amount=500)
    assert too_much.json()["code"] == "refund_too_high"
    assert too_much.json()["refundable"] == 400

    response = await refund(client, manager, order, method="cash", amount=50, reason="cold rice")

    body = response.json()
    assert response.status_code == 201
    assert body["status"] == "paid"
    assert body["amountPaid"] == 350
    assert body["payments"][-1]["kind"] == "refund"
    assert body["payments"][-1]["note"] == "cold rice"


async def test_cancelling_needs_the_money_back_first(
    client: AsyncClient, manager: User, cashier: User, menu: dict[str, Food]
) -> None:
    order = await place(client, manager, [(menu["borhani"], 1)], orderType="takeaway")
    await pay(client, cashier, order, method="card")
    cancel = {"status": "cancelled", "note": "customer left"}
    url = f"/orders/{order['id']}/status"

    blocked = await client.post(url, headers=auth_header(manager), json=cancel)
    assert blocked.json()["code"] == "refund_required"

    await refund(client, manager, order, method="card", amount=80)
    response = await client.post(url, headers=auth_header(manager), json=cancel)
    assert response.json()["status"] == "cancelled"


async def test_items_cant_drop_below_what_was_paid(
    client: AsyncClient, manager: User, cashier: User, menu: dict[str, Food]
) -> None:
    order = await place(client, manager, [(menu["kacchi"], 1)], orderType="takeaway")
    await pay(client, cashier, order, method="card")

    response = await client.put(
        f"/orders/{order['id']}/items",
        headers=auth_header(manager),
        json={"items": [{"foodId": menu["borhani"].id, "quantity": 1}]},
    )

    assert response.json()["code"] == "refund_required"
    unchanged = await client.get(f"/orders/{order['id']}", headers=auth_header(manager))
    assert unchanged.json()["total"] == 400


# receipt


async def test_bill_then_receipt(
    client: AsyncClient,
    manager: User,
    cashier: User,
    menu: dict[str, Food],
    table: DiningTable,
) -> None:
    await client.patch(
        "/restaurant",
        headers=auth_header(manager),
        json={"name": "Kacchi Bhai", "taxId": "000123456-0101", "vatPercent": 5},
    )
    order = await place(
        client, manager, [(menu["kacchi"], 1)], tableId=table.id, customerName="<b>Rafi</b>"
    )
    url = f"/orders/{order['id']}/receipt"

    bill = await client.get(url, headers=auth_header(manager))
    assert bill.status_code == 200
    assert bill.headers["content-type"].startswith("text/html")
    assert "<h2>BILL</h2>" in bill.text
    assert "Kacchi Bhai" in bill.text
    assert "BIN: 000123456-0101" in bill.text
    assert "&lt;b&gt;Rafi&lt;/b&gt;" in bill.text
    assert "window.print" not in bill.text

    await serve(client, manager, order)
    await pay(client, cashier, order, method="cash", tendered=500)
    receipt = await client.get(url + "?print=true", headers=auth_header(cashier))
    assert "<h2>RECEIPT</h2>" in receipt.text
    assert "৳420.00" in receipt.text
    assert "Change" in receipt.text
    assert "window.print" in receipt.text


async def test_no_receipt_for_cancelled_orders(
    client: AsyncClient, manager: User, menu: dict[str, Food]
) -> None:
    order = await place(client, manager, [(menu["borhani"], 1)], orderType="takeaway")
    await client.post(
        f"/orders/{order['id']}/status",
        headers=auth_header(manager),
        json={"status": "cancelled", "note": "mistake"},
    )

    response = await client.get(f"/orders/{order['id']}/receipt", headers=auth_header(manager))

    assert response.status_code == 409


async def test_receipt_needs_login(client: AsyncClient) -> None:
    response = await client.get("/orders/1/receipt")

    assert response.status_code == 401


# reports


async def test_vat_and_refunds_are_not_profit(
    client: AsyncClient, manager: User, cashier: User, menu: dict[str, Food]
) -> None:
    await set_rates(client, manager, vat=10, service=0)
    first = await place(client, manager, [(menu["kacchi"], 1)], orderType="takeaway")
    # a wrong payment fixed before the order was paid isn't a refund
    await pay(client, cashier, first, method="card", amount=100)
    await refund(client, manager, first, method="card", amount=100)
    await serve(client, manager, first)
    await pay(client, cashier, first, method="cash")
    second = await place(client, manager, [(menu["borhani"], 1)], orderType="takeaway")
    await serve(client, manager, second)
    await pay(client, cashier, second, method="cash")
    await refund(client, manager, second, method="cash", amount=30)

    sales = (await client.get("/reports/sales", headers=auth_header(manager))).json()
    dashboard = (await client.get("/dashboard", headers=auth_header(manager))).json()

    # 440 + 88 sales, 40 + 8 vat, 30 refunded
    for summary in (sales["totals"], dashboard["today"]):
        assert summary["sales"] == 528
        assert summary["vat"] == 48
        assert summary["refunds"] == 30
        assert summary["profit"] == 450
