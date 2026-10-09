"""Fan out of live events (order and booking changes) to the websocket connections of
this process, and optionally to the other instances through postgres."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import asynccontextmanager, suppress
from typing import Any, Protocol

import asyncpg
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import settings
from app.core.database import engine as default_engine

logger = logging.getLogger(__name__)

type Event = dict[str, Any]

# tells a connection it missed something and should send a fresh snapshot
RESYNC: Event = {"event": "resync"}

# a screen that can't keep up gets a snapshot instead of an ever growing backlog
QUEUE_SIZE = 200


class Subscriber:
    def __init__(self, topics: Iterable[str]) -> None:
        self.topics = frozenset(topics)
        self._queue: asyncio.Queue[Event] = asyncio.Queue(QUEUE_SIZE)

    def put(self, event: Event) -> None:
        if event is not RESYNC and event.get("topic") not in self.topics:
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            while not self._queue.empty():
                self._queue.get_nowait()
            self._queue.put_nowait(RESYNC)

    async def get(self) -> Event:
        return await self._queue.get()


class Relay(Protocol):
    """Passes events between processes, see PostgresRelay."""

    async def publish(self, event: Event) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...


class Hub:
    def __init__(self, relay: Relay | None = None) -> None:
        self.relay = relay
        self._subscribers: set[Subscriber] = set()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    @asynccontextmanager
    async def subscribe(self, topics: Iterable[str]) -> AsyncIterator[Subscriber]:
        subscriber = Subscriber(topics)
        first = not self._subscribers
        self._subscribers.add(subscriber)
        try:
            # only listen to other processes while someone here is watching
            if first and self.relay:
                await self.relay.start()
            yield subscriber
        finally:
            self._subscribers.discard(subscriber)
            if not self._subscribers and self.relay:
                await self.relay.stop()

    def deliver(self, event: Event) -> None:
        for subscriber in list(self._subscribers):
            subscriber.put(event)

    def resync(self) -> None:
        self.deliver(RESYNC)

    async def publish(self, event: Event) -> None:
        if self.relay:
            # comes back to this process through the relay like to every other one
            await self.relay.publish(event)
        else:
            self.deliver(event)

    async def close(self) -> None:
        if self.relay:
            await self.relay.stop()


CHANNEL = "live_events"
# postgres refuses NOTIFY payloads of 8000 bytes or more
NOTIFY_LIMIT = 7900


async def _connect_direct() -> asyncpg.Connection:
    # LISTEN needs its own direct connection, neon's pooler (pgbouncer) can't do it
    url = settings.migration_database_url
    ssl = url.query.get("ssl")
    return await asyncpg.connect(
        user=url.username,
        password=url.password,
        host=url.host,
        port=url.port,
        database=url.database,
        **({"ssl": ssl} if ssl else {}),
    )


class PostgresRelay:
    """Passes events between app instances with postgres LISTEN/NOTIFY.

    The listening connection is only open while this instance has websocket clients,
    no reason to wake neon up for nobody. Neon still drops it when the database suspends,
    then it reconnects and the screens get a fresh snapshot.
    """

    def __init__(
        self,
        hub: Hub,
        engine: AsyncEngine | None = None,
        connect: Callable[[], Awaitable[asyncpg.Connection]] = _connect_direct,
        retry_delay: float = 1.0,
        max_retry_delay: float = 30.0,
        wait_for_listen: float = 5.0,
    ) -> None:
        self.hub = hub
        self.engine = engine
        self.connect = connect
        self.retry_delay = retry_delay
        self.max_retry_delay = max_retry_delay
        self.wait_for_listen = wait_for_listen
        self.connection: asyncpg.Connection | None = None
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._listening = asyncio.Event()
        self._started = False

    async def publish(self, event: Event) -> None:
        payload = json.dumps(event, separators=(",", ":"))
        if len(payload.encode()) > NOTIFY_LIMIT:
            # a huge order, screens fetch it themselves
            payload = json.dumps({**event, "data": {"id": event["data"]["id"]}, "partial": True})
        engine = self.engine or default_engine
        async with engine.begin() as conn:
            await conn.execute(select(func.pg_notify(CHANNEL, payload)))

    async def start(self) -> None:
        async with self._lock:
            if self._task is not None:
                return
            self._started = False
            self._listening.clear()
            self._task = asyncio.create_task(self._run())
            # a moment for the first LISTEN, so the first snapshot doesn't miss anything
            with suppress(TimeoutError):
                async with asyncio.timeout(self.wait_for_listen):
                    await self._listening.wait()
            self._started = True

    async def stop(self) -> None:
        async with self._lock:
            task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    def _on_notify(self, _conn: object, _pid: int, _channel: str, payload: str) -> None:
        try:
            self.hub.deliver(json.loads(payload))
        except ValueError:
            logger.warning("ignoring a live event that isn't json")

    async def _run(self) -> None:
        delay = self.retry_delay
        while True:
            try:
                self.connection = await self.connect()
                lost = asyncio.Event()
                self.connection.add_termination_listener(lambda _conn, lost=lost: lost.set())
                await self.connection.add_listener(CHANNEL, self._on_notify)
                if self._started:
                    # back after a gap, screens may have missed events in the meantime
                    self.hub.resync()
                self._listening.set()
                delay = self.retry_delay
                await lost.wait()
                logger.warning("live relay lost its database connection, reconnecting")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("live relay can't listen, retrying in %ss", delay)
            finally:
                if self.connection is not None:
                    self.connection.terminate()
                    self.connection = None
            await asyncio.sleep(delay)
            delay = min(delay * 2, self.max_retry_delay)


def create_hub() -> Hub:
    hub = Hub()
    if settings.live_backend == "postgres":
        hub.relay = PostgresRelay(hub)
    return hub


hub = create_hub()
