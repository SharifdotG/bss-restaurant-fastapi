from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import anyio
import httpx
import jwt
import pytest
from httpx import AsyncClient
from httpx_ws import AsyncWebSocketSession, WebSocketDisconnect, aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import live as live_api
from app.core import live as live_core
from app.core.config import settings
from app.core.live import RESYNC, Subscriber, hub
from app.core.security import ALGORITHM
from app.core.timeutils import business_date, restaurant_tz
from app.main import app
from app.models import DiningTable, Food, User, UserRole
from tests.conftest import UserFactory, auth_header

pytestmark = pytest.mark.anyio


@pytest.fixture
async def ws_client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=ASGIWebSocketTransport(app), base_url="http://test/api/v1"
    ) as client:
        yield client


@pytest.fixture
async def waiter(make_user: UserFactory) -> User:
    return await make_user(UserRole.WAITER, first_name="Wes", last_name="Lee")


@pytest.fixture
async def setup(session: AsyncSession) -> dict:
    table = DiningTable(number="T1", seats=4)
    food = Food(name="Dal", price=Decimal("80"))
    session.add_all([table, food])
    await session.commit()
    return {"table": table.id, "food": food.id}


def token(user: User, seconds: int | None = None) -> str:
    if seconds is None:
        return auth_header(user)["Authorization"].split()[1]
    now = datetime.now(UTC)
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(seconds=seconds),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


@asynccontextmanager
async def feed(
    ws_client: httpx.AsyncClient, user: User, topics: str | None = None
) -> AsyncIterator[AsyncWebSocketSession]:
    """Connected, authenticated and past the snapshot."""
    params = f"?topics={topics}" if topics else ""
    async with aconnect_ws(f"http://test/api/v1/live{params}", ws_client) as ws:
        await ws.send_json({"type": "auth", "token": token(user)})
        assert (await ws.receive_json(timeout=5))["event"] == "authenticated"
        ws.snapshot = await ws.receive_json(timeout=5)
        yield ws


async def closed_with(ws: AsyncWebSocketSession) -> tuple[int, str]:
    with pytest.raises(WebSocketDisconnect) as info:
        while True:
            await ws.receive_json(timeout=5)
    return info.value.code, info.value.reason


async def place_order(client: AsyncClient, user: User, setup: dict) -> dict:
    body = {"tableId": setup["table"], "items": [{"foodId": setup["food"], "quantity": 2}]}
    response = await client.post("/orders", headers=auth_header(user), json=body)
    assert response.status_code == 201, response.text
    return response.json()


# connecting


@pytest.mark.parametrize(
    ("first_message", "code", "reason"),
    [
        ({"type": "hello"}, 4401, 'send {"type": "auth", "token": "<access token>"}'),
        ({"type": "auth", "token": "nope"}, 4401, "invalid_token"),
        (["not", "an", "object"], 4400, "messages must be json objects"),
    ],
)
async def test_first_message_must_authenticate(
    ws_client: httpx.AsyncClient, first_message, code: int, reason: str
) -> None:
    async with aconnect_ws("http://test/api/v1/live", ws_client) as ws:
        await ws.send_json(first_message)
        assert await closed_with(ws) == (code, reason)


async def test_silent_clients_are_dropped(
    ws_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(live_api, "AUTH_TIMEOUT", 0.2)
    async with aconnect_ws("http://test/api/v1/live", ws_client) as ws:
        assert await closed_with(ws) == (4401, "no auth message")


async def test_expired_and_inactive_users(
    ws_client: httpx.AsyncClient, make_user: UserFactory
) -> None:
    for user, reason in [
        (await make_user(), "token_expired"),
        (await make_user(is_active=False), "invalid_token"),
    ]:
        async with aconnect_ws("http://test/api/v1/live", ws_client) as ws:
            seconds = -10 if reason == "token_expired" else None
            await ws.send_json({"type": "auth", "token": token(user, seconds)})
            assert await closed_with(ws) == (4401, reason)


async def test_topics_depend_on_the_role(
    ws_client: httpx.AsyncClient, make_user: UserFactory
) -> None:
    chef = await make_user(UserRole.CHEF)
    async with feed(ws_client, chef) as ws:
        assert set(ws.snapshot) == {"event", "at", "orders"}

    for topics, code in [("reservations", 4403), ("orders,menu", 4400)]:
        async with aconnect_ws(f"http://test/api/v1/live?topics={topics}", ws_client) as ws:
            await ws.send_json({"type": "auth", "token": token(chef)})
            await ws.receive_json(timeout=5)
            assert (await closed_with(ws))[0] == code


# events


async def test_snapshot_then_changes(
    ws_client: httpx.AsyncClient, client: AsyncClient, waiter: User, setup: dict
) -> None:
    earlier = await place_order(client, waiter, setup)

    async with feed(ws_client, waiter) as ws:
        assert ws.snapshot["event"] == "snapshot"
        assert [o["orderNumber"] for o in ws.snapshot["orders"]] == [earlier["orderNumber"]]
        assert ws.snapshot["reservations"] == []

        order = await place_order(client, waiter, setup)
        event = await ws.receive_json(timeout=5)
        assert event["event"] == "order.created"
        assert event["topic"] == "orders"
        assert event["data"]["id"] == order["id"]
        assert event["data"]["items"] == [{"foodName": "Dal", "quantity": 2, "notes": None}]
        assert event["data"]["table"] == {"id": setup["table"], "number": "T1"}

        await client.post(
            f"/orders/{order['id']}/status",
            headers=auth_header(waiter),
            json={"status": "confirmed"},
        )
        event = await ws.receive_json(timeout=5)
        assert event["event"] == "order.updated"
        assert event["data"]["status"] == "confirmed"


async def test_bookings_and_topic_filter(
    ws_client: httpx.AsyncClient, client: AsyncClient, waiter: User, setup: dict
) -> None:
    starts_at = datetime.combine(
        business_date() + timedelta(days=1), datetime.min.time(), tzinfo=restaurant_tz()
    ) + timedelta(hours=19)

    async with feed(ws_client, waiter, topics="reservations") as ws:
        assert "orders" not in ws.snapshot
        await place_order(client, waiter, setup)
        response = await client.post(
            "/reservations",
            headers=auth_header(waiter),
            json={
                "startsAt": starts_at.isoformat(),
                "partySize": 2,
                "customerName": "Rahim",
                "customerPhone": "01711000000",
            },
        )
        assert response.status_code == 201

        # the order never shows up, the booking does
        event = await ws.receive_json(timeout=5)
        assert event["event"] == "reservation.created"
        assert event["data"]["table"]["number"] == "T1"
        assert event["data"]["customerPhone"] == "01711000000"


async def test_public_orders_reach_the_staff(
    ws_client: httpx.AsyncClient, client: AsyncClient, waiter: User, setup: dict, session
) -> None:
    table = await session.get(DiningTable, setup["table"])
    async with feed(ws_client, waiter, topics="orders") as ws:
        response = await client.post(
            f"/public/tables/{table.qr_token}/orders",
            json={"items": [{"foodId": setup["food"], "quantity": 1}]},
        )
        assert response.status_code == 201
        event = await ws.receive_json(timeout=5)
        assert event["event"] == "order.created"
        assert event["data"]["source"] == "qr"


# keeping the connection


async def test_ping_and_unknown_messages(ws_client: httpx.AsyncClient, waiter: User) -> None:
    async with feed(ws_client, waiter) as ws:
        await ws.send_json({"type": "ping"})
        assert await ws.receive_json(timeout=5) == {"event": "pong"}
        await ws.send_json({"type": "dance"})
        assert (await ws.receive_json(timeout=5))["event"] == "error"


async def test_server_pings_when_quiet(
    ws_client: httpx.AsyncClient, waiter: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(live_api, "KEEPALIVE", 0.1)
    async with feed(ws_client, waiter) as ws:
        assert await ws.receive_json(timeout=5) == {"event": "ping"}


async def test_connection_ends_with_the_token_unless_renewed(
    ws_client: httpx.AsyncClient, waiter: User, make_user: UserFactory
) -> None:
    async with aconnect_ws("http://test/api/v1/live", ws_client) as ws:
        await ws.send_json({"type": "auth", "token": token(waiter, seconds=1)})
        assert (await ws.receive_json(timeout=5))["expiresIn"] <= 1
        await ws.receive_json(timeout=5)  # snapshot
        assert await closed_with(ws) == (4401, "token_expired")

    async with aconnect_ws("http://test/api/v1/live", ws_client) as ws:
        await ws.send_json({"type": "auth", "token": token(waiter, seconds=3)})
        await ws.receive_json(timeout=5)
        await ws.receive_json(timeout=5)
        await ws.send_json({"type": "auth", "token": token(waiter)})
        renewed = await ws.receive_json(timeout=5)
        assert renewed["event"] == "authenticated"
        assert renewed["expiresIn"] > 60

        # someone else's token doesn't take over the connection
        other = await make_user()
        await ws.send_json({"type": "auth", "token": token(other)})
        assert await closed_with(ws) == (4401, "a connection belongs to one user")


async def test_resync_sends_a_new_snapshot(ws_client: httpx.AsyncClient, waiter: User) -> None:
    async with feed(ws_client, waiter) as ws:
        hub.resync()
        assert (await ws.receive_json(timeout=5))["event"] == "snapshot"
        assert hub.subscriber_count == 1

    # the server notices the disconnect a moment later
    for _ in range(50):
        if hub.subscriber_count == 0:
            break
        await anyio.sleep(0.02)
    assert hub.subscriber_count == 0


async def test_a_broken_feed_does_not_fail_the_request(
    client: AsyncClient, waiter: User, setup: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(event) -> None:
        raise ConnectionError("relay is down")

    monkeypatch.setattr(hub, "publish", broken)
    await place_order(client, waiter, setup)


# the hub itself


async def test_slow_subscribers_get_a_resync(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live_core, "QUEUE_SIZE", 2)
    subscriber = Subscriber({"orders"})
    subscriber.put({"topic": "reservations"})
    for n in range(3):
        subscriber.put({"topic": "orders", "n": n})

    assert subscriber._queue.qsize() == 1
    assert subscriber._queue.get_nowait() is RESYNC
