import pytest
from httpx import AsyncClient

from app.models import UserRole
from tests.conftest import UserFactory, auth_header

pytestmark = pytest.mark.anyio


def new_user(**overrides) -> dict:
    return {
        "email": "new@example.com",
        "password": "Password123",
        "firstName": "New",
        "lastName": "Person",
        "role": "waiter",
    } | overrides


async def test_admin_creates_user(client: AsyncClient, make_user: UserFactory) -> None:
    admin = await make_user(UserRole.ADMIN)

    response = await client.post(
        "/users", headers=auth_header(admin), json=new_user(email="New@Example.COM")
    )

    assert response.status_code == 201
    assert response.json()["email"] == "new@example.com"
    login = await client.post(
        "/auth/login", json={"email": "new@example.com", "password": "Password123"}
    )
    assert login.status_code == 200


async def test_duplicate_email_is_a_conflict(client: AsyncClient, make_user: UserFactory) -> None:
    admin = await make_user(UserRole.ADMIN, email="admin@example.com")

    response = await client.post(
        "/users", headers=auth_header(admin), json=new_user(email="ADMIN@example.com")
    )

    assert response.status_code == 409
    assert response.json()["code"] == "email_taken"


@pytest.mark.parametrize("role", [UserRole.WAITER, UserRole.CHEF, UserRole.CASHIER])
async def test_staff_cannot_manage_users(
    client: AsyncClient, make_user: UserFactory, role: UserRole
) -> None:
    user = await make_user(role)

    assert (await client.get("/users", headers=auth_header(user))).status_code == 403
    assert (
        await client.post("/users", headers=auth_header(user), json=new_user())
    ).status_code == 403


async def test_manager_can_only_manage_staff(client: AsyncClient, make_user: UserFactory) -> None:
    manager = await make_user(UserRole.MANAGER)
    admin = await make_user(UserRole.ADMIN)
    headers = auth_header(manager)

    ok = await client.post("/users", headers=headers, json=new_user(role="chef"))
    assert ok.status_code == 201

    for role in ("admin", "manager"):
        denied = await client.post(
            "/users", headers=headers, json=new_user(email=f"{role}2@example.com", role=role)
        )
        assert denied.status_code == 403

    promote = await client.patch(
        f"/users/{ok.json()['id']}", headers=headers, json={"role": "manager"}
    )
    assert promote.status_code == 403
    touch_admin = await client.patch(f"/users/{admin.id}", headers=headers, json={"firstName": "X"})
    assert touch_admin.status_code == 403


async def test_list_users_filters_and_sorts(client: AsyncClient, make_user: UserFactory) -> None:
    admin = await make_user(UserRole.ADMIN, email="zed@example.com", first_name="Zed")
    await make_user(UserRole.CHEF, email="amy@example.com", first_name="Amy")
    await make_user(UserRole.CHEF, email="bob@example.com", first_name="Bob", is_active=False)
    headers = auth_header(admin)

    chefs = (await client.get("/users?role=chef&sort=firstName", headers=headers)).json()
    assert [u["firstName"] for u in chefs["items"]] == ["Amy", "Bob"]

    active_chefs = (await client.get("/users?role=chef&isActive=true", headers=headers)).json()
    assert active_chefs["total"] == 1

    found = (await client.get("/users?search=ZED", headers=headers)).json()
    assert [u["email"] for u in found["items"]] == ["zed@example.com"]

    page = (await client.get("/users?size=2&page=2&sort=email", headers=headers)).json()
    assert page["total"] == 3
    assert page["pages"] == 2
    assert [u["email"] for u in page["items"]] == ["zed@example.com"]

    bad_sort = await client.get("/users?sort=passwordHash", headers=headers)
    assert bad_sort.status_code == 400


async def test_cannot_lock_out_the_last_admin(client: AsyncClient, make_user: UserFactory) -> None:
    admin = await make_user(UserRole.ADMIN)
    headers = auth_header(admin)

    own_role = await client.patch(f"/users/{admin.id}", headers=headers, json={"role": "waiter"})
    assert own_role.status_code == 400
    assert (await client.delete(f"/users/{admin.id}", headers=headers)).status_code == 400

    other = await make_user(UserRole.ADMIN)
    assert (await client.delete(f"/users/{other.id}", headers=headers)).status_code == 204
    # now `admin` is the only one left again
    demote = await client.patch(
        f"/users/{admin.id}", headers=auth_header(admin), json={"isActive": False}
    )
    assert demote.status_code == 400


async def test_deactivate_signs_the_user_out(client: AsyncClient, make_user: UserFactory) -> None:
    admin = await make_user(UserRole.ADMIN)
    waiter = await make_user(email="w@example.com")
    tokens = (
        await client.post("/auth/login", json={"email": "w@example.com", "password": "Password123"})
    ).json()

    response = await client.delete(f"/users/{waiter.id}", headers=auth_header(admin))

    assert response.status_code == 204
    refresh = await client.post("/auth/refresh", json={"refreshToken": tokens["refreshToken"]})
    assert refresh.status_code == 401
    shown = (await client.get(f"/users/{waiter.id}", headers=auth_header(admin))).json()
    assert shown["isActive"] is False


async def test_reset_password(client: AsyncClient, make_user: UserFactory) -> None:
    manager = await make_user(UserRole.MANAGER)
    waiter = await make_user(email="w@example.com")

    response = await client.post(
        f"/users/{waiter.id}/reset-password",
        headers=auth_header(manager),
        json={"newPassword": "Changed123"},
    )

    assert response.status_code == 204
    login = await client.post(
        "/auth/login", json={"email": "w@example.com", "password": "Changed123"}
    )
    assert login.status_code == 200


async def test_get_missing_user(client: AsyncClient, make_user: UserFactory) -> None:
    admin = await make_user(UserRole.ADMIN)

    response = await client.get("/users/9999", headers=auth_header(admin))

    assert response.status_code == 404
