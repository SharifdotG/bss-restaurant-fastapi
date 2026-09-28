import pytest
from httpx import AsyncClient

from app.models import User, UserRole
from tests.conftest import UserFactory, auth_header

pytestmark = pytest.mark.anyio


@pytest.fixture
async def manager(make_user: UserFactory) -> User:
    return await make_user(UserRole.MANAGER)


async def create_table(client: AsyncClient, manager: User, number: str = "T1", **extra) -> dict:
    response = await client.post(
        "/tables", headers=auth_header(manager), json={"number": number, "seats": 4, **extra}
    )
    assert response.status_code == 201, response.text
    return response.json()


def employee_payload(**overrides) -> dict:
    return {
        "firstName": "Rahim",
        "lastName": "Uddin",
        "designation": "Waiter",
        "joinDate": "2025-01-15",
    } | overrides


async def create_employee(client: AsyncClient, manager: User, **overrides) -> dict:
    response = await client.post(
        "/employees", headers=auth_header(manager), json=employee_payload(**overrides)
    )
    assert response.status_code == 201, response.text
    return response.json()


# tables


async def test_create_table(client: AsyncClient, manager: User) -> None:
    table = await create_table(client, manager, "T1", location="Rooftop")

    assert table["seats"] == 4
    assert table["location"] == "Rooftop"
    assert len(table["qrToken"]) >= 20
    assert table["employees"] == []


async def test_table_numbers_are_unique(client: AsyncClient, manager: User) -> None:
    await create_table(client, manager, "t1")

    response = await client.post(
        "/tables", headers=auth_header(manager), json={"number": "T1", "seats": 2}
    )

    assert response.status_code == 409


@pytest.mark.parametrize("seats", [0, 51])
async def test_seat_limits(client: AsyncClient, manager: User, seats: int) -> None:
    response = await client.post(
        "/tables", headers=auth_header(manager), json={"number": "T1", "seats": seats}
    )

    assert response.status_code == 422


async def test_regenerate_qr_token(client: AsyncClient, manager: User) -> None:
    table = await create_table(client, manager)

    response = await client.post(f"/tables/{table['id']}/qr-token", headers=auth_header(manager))

    assert response.json()["qrToken"] != table["qrToken"]


async def test_list_tables(client: AsyncClient, manager: User) -> None:
    await create_table(client, manager, "T1", seats=2)
    await create_table(client, manager, "T2", seats=6, location="Garden")
    await create_table(client, manager, "T3", seats=8, isActive=False)
    headers = auth_header(manager)

    big = (await client.get("/tables?minSeats=5&isActive=true", headers=headers)).json()
    assert [t["number"] for t in big["items"]] == ["T2"]

    garden = (await client.get("/tables?search=garden", headers=headers)).json()
    assert garden["total"] == 1

    by_seats = (await client.get("/tables?sort=-seats", headers=headers)).json()
    assert [t["number"] for t in by_seats["items"]] == ["T3", "T2", "T1"]


async def test_delete_table(client: AsyncClient, manager: User) -> None:
    table = await create_table(client, manager)

    response = await client.delete(f"/tables/{table['id']}", headers=auth_header(manager))

    assert response.status_code == 204
    assert (
        await client.get(f"/tables/{table['id']}", headers=auth_header(manager))
    ).status_code == 404


# employees


async def test_create_employee_without_account(client: AsyncClient, manager: User) -> None:
    employee = await create_employee(client, manager, phone="01711-000111", gender="male")

    assert employee["fullName"] == "Rahim Uddin"
    assert employee["phone"] == "01711000111"
    assert employee["account"] is None
    assert employee["tables"] == []


async def test_any_number_of_employees_without_nid(client: AsyncClient, manager: User) -> None:
    # the old api broke on the second employee without an NID
    await create_employee(client, manager)
    await create_employee(client, manager, firstName="Karim")

    listed = (await client.get("/employees", headers=auth_header(manager))).json()
    assert listed["total"] == 2


async def test_nid_and_phone_are_unique(client: AsyncClient, manager: User) -> None:
    await create_employee(client, manager, nid="1990123456", phone="01711000111")

    for duplicate in ({"nid": "1990123456"}, {"phone": "01711000111"}):
        response = await client.post(
            "/employees", headers=auth_header(manager), json=employee_payload(**duplicate)
        )
        assert response.status_code == 409


async def test_employee_with_login_account(client: AsyncClient, manager: User) -> None:
    employee = await create_employee(
        client,
        manager,
        email="rahim@example.com",
        account={"role": "waiter", "password": "Waiter123"},
    )

    assert employee["account"]["email"] == "rahim@example.com"
    assert employee["account"]["role"] == "waiter"
    login = await client.post(
        "/auth/login", json={"email": "rahim@example.com", "password": "Waiter123"}
    )
    assert login.status_code == 200
    assert login.json()["user"]["fullName"] == "Rahim Uddin"


async def test_account_needs_an_email(client: AsyncClient, manager: User) -> None:
    response = await client.post(
        "/employees",
        headers=auth_header(manager),
        json=employee_payload(account={"role": "waiter", "password": "Waiter123"}),
    )

    assert response.status_code == 422


async def test_failed_account_leaves_no_employee_behind(
    client: AsyncClient, manager: User, make_user: UserFactory
) -> None:
    await make_user(email="taken@example.com")

    response = await client.post(
        "/employees",
        headers=auth_header(manager),
        json=employee_payload(
            email="taken@example.com", account={"role": "chef", "password": "Chef12345"}
        ),
    )

    assert response.status_code == 409
    assert (await client.get("/employees", headers=auth_header(manager))).json()["total"] == 0


async def test_manager_cannot_create_manager_accounts(client: AsyncClient, manager: User) -> None:
    response = await client.post(
        "/employees",
        headers=auth_header(manager),
        json=employee_payload(
            email="boss@example.com", account={"role": "manager", "password": "Manager123"}
        ),
    )

    assert response.status_code == 403


async def test_add_account_later(client: AsyncClient, manager: User) -> None:
    employee = await create_employee(client, manager, email="chef@example.com")
    url = f"/employees/{employee['id']}/account"

    response = await client.post(
        url, headers=auth_header(manager), json={"role": "chef", "password": "Chef12345"}
    )
    assert response.json()["account"]["role"] == "chef"

    again = await client.post(
        url, headers=auth_header(manager), json={"role": "chef", "password": "Chef12345"}
    )
    assert again.json()["code"] == "account_exists"


async def test_updating_names_updates_the_account(client: AsyncClient, manager: User) -> None:
    employee = await create_employee(
        client, manager, email="r@example.com", account={"role": "waiter", "password": "Waiter123"}
    )

    await client.patch(
        f"/employees/{employee['id']}", headers=auth_header(manager), json={"lastName": "Mia"}
    )

    login = await client.post(
        "/auth/login", json={"email": "r@example.com", "password": "Waiter123"}
    )
    assert login.json()["user"]["fullName"] == "Rahim Mia"


@pytest.mark.parametrize(
    "dates",
    [{"dateOfBirth": "2999-01-01"}, {"dateOfBirth": "2000-01-01", "joinDate": "1999-01-01"}],
)
async def test_date_validation(client: AsyncClient, manager: User, dates: dict) -> None:
    response = await client.post(
        "/employees", headers=auth_header(manager), json=employee_payload(**dates)
    )

    assert response.status_code == 422


async def test_waiters_cannot_see_employee_records(
    client: AsyncClient, make_user: UserFactory
) -> None:
    waiter = await make_user(UserRole.WAITER)

    assert (await client.get("/employees", headers=auth_header(waiter))).status_code == 403


# assignments


async def test_assign_employees_to_table(client: AsyncClient, manager: User) -> None:
    table = await create_table(client, manager)
    rahim = await create_employee(client, manager)
    karim = await create_employee(client, manager, firstName="Karim")
    url = f"/tables/{table['id']}/employees"
    headers = auth_header(manager)

    response = await client.put(
        url, headers=headers, json={"employeeIds": [rahim["id"], karim["id"], rahim["id"]]}
    )
    assert response.status_code == 200
    assert [e["fullName"] for e in response.json()["employees"]] == ["Karim Uddin", "Rahim Uddin"]

    # sending the list again replaces it
    response = await client.put(url, headers=headers, json={"employeeIds": [karim["id"]]})
    assert [e["id"] for e in response.json()["employees"]] == [karim["id"]]

    shown = (await client.get(f"/employees/{karim['id']}", headers=headers)).json()
    assert shown["tables"] == [{"id": table["id"], "number": "T1"}]

    served = (await client.get(f"/tables?employeeId={karim['id']}", headers=headers)).json()
    assert served["total"] == 1

    cleared = await client.put(url, headers=headers, json={"employeeIds": []})
    assert cleared.json()["employees"] == []


async def test_assigning_unknown_employees(client: AsyncClient, manager: User) -> None:
    table = await create_table(client, manager)

    response = await client.put(
        f"/tables/{table['id']}/employees", headers=auth_header(manager), json={"employeeIds": [42]}
    )

    assert response.status_code == 400
    assert response.json()["employeeIds"] == [42]


async def test_deactivating_employee(client: AsyncClient, manager: User) -> None:
    table = await create_table(client, manager)
    employee = await create_employee(
        client, manager, email="w@example.com", account={"role": "waiter", "password": "Waiter123"}
    )
    headers = auth_header(manager)
    await client.put(
        f"/tables/{table['id']}/employees", headers=headers, json={"employeeIds": [employee["id"]]}
    )

    response = await client.delete(f"/employees/{employee['id']}", headers=headers)

    assert response.status_code == 204
    shown = (await client.get(f"/employees/{employee['id']}", headers=headers)).json()
    assert shown["isActive"] is False
    assert shown["account"]["isActive"] is False
    assert shown["tables"] == []
    login = await client.post(
        "/auth/login", json={"email": "w@example.com", "password": "Waiter123"}
    )
    assert login.status_code == 403
