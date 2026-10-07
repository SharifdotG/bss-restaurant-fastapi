"""Fan out of live events (order and booking changes) to the websocket connections of
this process."""

import asyncio
import logging
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from typing import Any, Protocol

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


hub = Hub()
