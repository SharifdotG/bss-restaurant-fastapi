import asyncio
import json
from datetime import UTC, datetime
from typing import Annotated, Any

import jwt
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import get_current_user
from app.core.database import get_sessionmaker
from app.core.exceptions import AuthenticationError
from app.core.live import RESYNC, Subscriber, hub
from app.core.security import decode_access_token
from app.models import User, UserRole
from app.services.live import Topic, snapshot

router = APIRouter(tags=["live"])

SessionMaker = Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)]

# websocket close codes, 4000+ is free for applications. mirrors the http ones
BAD_REQUEST = 4400
UNAUTHORIZED = 4401
FORBIDDEN = 4403

AUTH_TIMEOUT = 10
# proxies drop quiet connections, a ping every now and then keeps them open
KEEPALIVE = 25

# the kitchen has no business with bookings
TOPICS_BY_ROLE = {UserRole.CHEF: {Topic.ORDERS}}


class Close(Exception):
    def __init__(self, code: int, reason: str) -> None:
        self.code = code
        self.reason = reason


class Connection:
    def __init__(self, websocket: WebSocket, sessions: SessionMaker) -> None:
        self.websocket = websocket
        self.sessions = sessions
        self.user: User | None = None
        self.expires_at = datetime.now(UTC)
        self._send_lock = asyncio.Lock()

    async def send(self, message: dict[str, Any]) -> None:
        async with self._send_lock:
            await self.websocket.send_json(message)

    async def receive(self) -> dict[str, Any]:
        text = await self.websocket.receive_text()
        try:
            message = json.loads(text)
        except ValueError:
            message = None
        if not isinstance(message, dict):
            raise Close(BAD_REQUEST, "messages must be json objects")
        return message

    async def authenticate(self, message: dict[str, Any]) -> None:
        token = message.get("token")
        if message.get("type") != "auth" or not isinstance(token, str):
            raise Close(UNAUTHORIZED, 'send {"type": "auth", "token": "<access token>"}')
        try:
            async with self.sessions() as session:
                user = await get_current_user(session, token)
            expires = decode_access_token(token)["exp"]
        except (AuthenticationError, jwt.InvalidTokenError) as exc:
            raise Close(UNAUTHORIZED, getattr(exc, "code", "invalid_token")) from None
        if self.user is not None and user.id != self.user.id:
            raise Close(UNAUTHORIZED, "a connection belongs to one user")

        self.user = user
        self.expires_at = datetime.fromtimestamp(expires, UTC)
        await self.send(
            {
                "event": "authenticated",
                "user": {"id": user.id, "fullName": user.full_name, "role": user.role},
                "expiresIn": self.seconds_left(),
            }
        )

    def seconds_left(self) -> int:
        return max(int((self.expires_at - datetime.now(UTC)).total_seconds()), 0)

    def topics(self, requested: str | None) -> frozenset[str]:
        allowed = TOPICS_BY_ROLE.get(self.user.role, set(Topic))
        if not requested:
            return frozenset(allowed)
        wanted = {name.strip() for name in requested.split(",") if name.strip()}
        if unknown := wanted - set(Topic):
            raise Close(BAD_REQUEST, f"unknown topics: {', '.join(sorted(unknown))}")
        if wanted - allowed:
            raise Close(FORBIDDEN, "your role can't follow these topics")
        return frozenset(wanted)

    async def send_snapshot(self, topics: frozenset[str]) -> None:
        async with self.sessions() as session:
            await self.send(await snapshot(session, topics))

    async def pump(self, subscriber: Subscriber, topics: frozenset[str]) -> None:
        while True:
            try:
                async with asyncio.timeout(KEEPALIVE):
                    event = await subscriber.get()
            except TimeoutError:
                await self.send({"event": "ping"})
                continue
            if event is RESYNC:
                await self.send_snapshot(topics)
            else:
                await self.send(event)

    async def listen(self) -> None:
        while True:
            try:
                async with asyncio.timeout(self.seconds_left()):
                    message = await self.receive()
            except TimeoutError:
                raise Close(UNAUTHORIZED, "token_expired") from None
            match message.get("type"):
                case "ping":
                    await self.send({"event": "pong"})
                case "auth":
                    # a fresh token keeps the connection going past the old one's expiry
                    await self.authenticate(message)
                case _:
                    await self.send({"event": "error", "detail": "unknown message type"})


@router.websocket("/live")
async def live(
    websocket: WebSocket,
    sessions: SessionMaker,
    topics: Annotated[str | None, Query(description="orders,reservations")] = None,
) -> None:
    """Order and booking changes as they happen, for kitchen and floor screens.

    Send `{"type": "auth", "token": "<access token>"}` first. Then the server sends a
    `snapshot` and after that every `order.created`, `order.updated`,
    `reservation.created` and `reservation.updated`. Send a new auth message before
    the token runs out to keep the connection.
    """
    await websocket.accept()
    connection = Connection(websocket, sessions)
    try:
        try:
            async with asyncio.timeout(AUTH_TIMEOUT):
                first = await connection.receive()
        except TimeoutError:
            raise Close(UNAUTHORIZED, "no auth message") from None
        await connection.authenticate(first)
        wanted = connection.topics(topics)

        # subscribe before the snapshot, so nothing that happens in between gets lost
        async with hub.subscribe(wanted) as subscriber:
            await connection.send_snapshot(wanted)
            async with asyncio.TaskGroup() as tasks:
                tasks.create_task(connection.pump(subscriber, wanted))
                tasks.create_task(connection.listen())
    except* WebSocketDisconnect:
        pass
    except* Close as group:
        close = group.exceptions[0]
        await websocket.close(close.code, close.reason)
