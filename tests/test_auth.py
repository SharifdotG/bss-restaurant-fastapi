from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.models import UserRole
from tests.conftest import DEFAULT_PASSWORD, UserFactory, auth_header

pytestmark = pytest.mark.anyio


async def login(client: AsyncClient, email: str, password: str = DEFAULT_PASSWORD):
    return await client.post("/auth/login", json={"email": email, "password": password})


async def test_login_returns_tokens_and_user(client: AsyncClient, make_user: UserFactory) -> None:
    user = await make_user(email="ada@example.com", role=UserRole.MANAGER)

    response = await login(client, "ADA@example.com")

    assert response.status_code == 200
    body = response.json()
    assert body["tokenType"] == "bearer"
    assert body["expiresIn"] == settings.access_token_expire_minutes * 60
    assert body["user"]["id"] == user.id
    assert body["user"]["role"] == "manager"
    assert body["user"]["lastLoginAt"] is not None
    assert "passwordHash" not in body["user"]


@pytest.mark.parametrize("email", ["ada@example.com", "nobody@example.com"])
async def test_login_with_wrong_credentials(
    client: AsyncClient, make_user: UserFactory, email: str
) -> None:
    await make_user(email="ada@example.com")

    response = await login(client, email, "WrongPass1")

    # same answer whether the user exists or not
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"


async def test_inactive_user_cannot_login(client: AsyncClient, make_user: UserFactory) -> None:
    await make_user(email="old@example.com", is_active=False)

    response = await login(client, "old@example.com")

    assert response.status_code == 403
    assert response.json()["code"] == "account_disabled"


async def test_refresh_rotates_the_token(client: AsyncClient, make_user: UserFactory) -> None:
    await make_user(email="ada@example.com")
    first = (await login(client, "ada@example.com")).json()

    response = await client.post("/auth/refresh", json={"refreshToken": first["refreshToken"]})

    assert response.status_code == 200
    assert response.json()["refreshToken"] != first["refreshToken"]


async def test_reusing_a_refresh_token_kills_the_session(
    client: AsyncClient, make_user: UserFactory
) -> None:
    await make_user(email="ada@example.com")
    first = (await login(client, "ada@example.com")).json()
    second = (
        await client.post("/auth/refresh", json={"refreshToken": first["refreshToken"]})
    ).json()

    reused = await client.post("/auth/refresh", json={"refreshToken": first["refreshToken"]})
    assert reused.status_code == 401

    # the legit token from the same login is gone too
    after = await client.post("/auth/refresh", json={"refreshToken": second["refreshToken"]})
    assert after.status_code == 401


async def test_sessions_on_other_devices_are_independent(
    client: AsyncClient, make_user: UserFactory
) -> None:
    await make_user(email="ada@example.com")
    phone = (await login(client, "ada@example.com")).json()
    laptop = (await login(client, "ada@example.com")).json()

    await client.post("/auth/logout", json={"refreshToken": phone["refreshToken"]})

    assert (
        await client.post("/auth/refresh", json={"refreshToken": phone["refreshToken"]})
    ).status_code == 401
    assert (
        await client.post("/auth/refresh", json={"refreshToken": laptop["refreshToken"]})
    ).status_code == 200


async def test_logout_all(client: AsyncClient, make_user: UserFactory) -> None:
    user = await make_user(email="ada@example.com")
    tokens = [(await login(client, "ada@example.com")).json() for _ in range(2)]

    response = await client.post("/auth/logout-all", headers=auth_header(user))

    assert response.status_code == 204
    for t in tokens:
        refresh = await client.post("/auth/refresh", json={"refreshToken": t["refreshToken"]})
        assert refresh.status_code == 401


async def test_me_requires_a_valid_token(client: AsyncClient, make_user: UserFactory) -> None:
    user = await make_user()

    assert (await client.get("/auth/me")).json()["code"] == "not_authenticated"
    bad = await client.get("/auth/me", headers={"Authorization": "Bearer nonsense"})
    assert bad.json()["code"] == "invalid_token"

    response = await client.get("/auth/me", headers=auth_header(user))
    assert response.status_code == 200
    assert response.json()["email"] == user.email


async def test_expired_access_token(client: AsyncClient, make_user: UserFactory) -> None:
    user = await make_user()
    past = datetime.now(UTC) - timedelta(hours=1)
    token = jwt.encode(
        {"sub": str(user.id), "type": "access", "iat": past, "exp": past + timedelta(minutes=5)},
        settings.secret_key,
        algorithm="HS256",
    )

    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.json()["code"] == "token_expired"


async def test_deactivated_user_token_stops_working(
    client: AsyncClient, make_user: UserFactory, session
) -> None:
    user = await make_user()
    headers = auth_header(user)
    user.is_active = False
    await session.commit()

    assert (await client.get("/auth/me", headers=headers)).status_code == 401


async def test_update_profile(client: AsyncClient, make_user: UserFactory) -> None:
    user = await make_user()

    response = await client.patch(
        "/auth/me",
        headers=auth_header(user),
        json={"firstName": "Ada", "lastName": "Lovelace", "phone": "017 1111-2222"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["fullName"] == "Ada Lovelace"
    assert body["phone"] == "01711112222"


async def test_phone_must_be_unique(client: AsyncClient, make_user: UserFactory) -> None:
    await make_user(phone="01711112222")
    user = await make_user()

    response = await client.patch(
        "/auth/me", headers=auth_header(user), json={"phone": "01711-112222"}
    )

    assert response.status_code == 409
    assert response.json()["code"] == "phone_taken"


async def test_change_password(client: AsyncClient, make_user: UserFactory) -> None:
    user = await make_user(email="ada@example.com")
    other_device = (await login(client, "ada@example.com")).json()

    wrong = await client.post(
        "/auth/me/password",
        headers=auth_header(user),
        json={"currentPassword": "nope", "newPassword": "NewPassword1"},
    )
    assert wrong.json()["code"] == "wrong_password"

    response = await client.post(
        "/auth/me/password",
        headers=auth_header(user),
        json={"currentPassword": DEFAULT_PASSWORD, "newPassword": "NewPassword1"},
    )
    assert response.status_code == 200
    assert response.json()["refreshToken"]

    assert (await login(client, "ada@example.com")).status_code == 401
    assert (await login(client, "ada@example.com", "NewPassword1")).status_code == 200
    stale = await client.post("/auth/refresh", json={"refreshToken": other_device["refreshToken"]})
    assert stale.status_code == 401


@pytest.mark.parametrize("password", ["short1", "onlyletters", "1234567890"])
async def test_weak_new_password_is_rejected(
    client: AsyncClient, make_user: UserFactory, password: str
) -> None:
    user = await make_user()

    response = await client.post(
        "/auth/me/password",
        headers=auth_header(user),
        json={"currentPassword": DEFAULT_PASSWORD, "newPassword": password},
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "newPassword"
