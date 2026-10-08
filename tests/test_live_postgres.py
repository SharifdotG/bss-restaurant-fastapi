from collections.abc import AsyncIterator

import anyio
import pytest
from sqlalchemy import func, select

from app.core.live import RESYNC, Hub, PostgresRelay
from tests.conftest import test_engine

pytestmark = pytest.mark.anyio


def instance() -> Hub:
    """One app instance, sharing the test database with the others."""
    hub = Hub()
    hub.relay = PostgresRelay(hub, engine=test_engine, retry_delay=0.05)
    return hub


@pytest.fixture
async def instances() -> AsyncIterator[tuple[Hub, Hub]]:
    first, second = instance(), instance()
    yield first, second
    await first.close()
    await second.close()


async def next_event(subscriber, seconds: float = 5):
    with anyio.fail_after(seconds):
        return await subscriber.get()


async def test_events_reach_other_instances(instances: tuple[Hub, Hub]) -> None:
    cashier_screen, kitchen = instances
    async with kitchen.subscribe({"orders"}) as subscriber:
        event = {"event": "order.created", "topic": "orders", "data": {"id": 1}, "at": "now"}
        await cashier_screen.publish(event)
        assert await next_event(subscriber) == event

        # this instance's own events come back through postgres too
        await kitchen.publish({**event, "data": {"id": 2}})
        assert (await next_event(subscriber))["data"] == {"id": 2}


async def test_big_events_are_cut_down(instances: tuple[Hub, Hub]) -> None:
    sender, receiver = instances
    async with receiver.subscribe({"orders"}) as subscriber:
        items = [{"foodName": "x" * 100, "quantity": 1}] * 100
        await sender.publish(
            {"event": "order.created", "topic": "orders", "data": {"id": 7, "items": items}}
        )
        event = await next_event(subscriber)
        assert event["data"] == {"id": 7}
        assert event["partial"] is True


async def test_listens_only_while_someone_watches(instances: tuple[Hub, Hub]) -> None:
    hub, _ = instances
    assert hub.relay.connection is None
    async with hub.subscribe({"orders"}), hub.subscribe({"reservations"}):
        assert hub.relay.connection is not None
    assert hub.relay.connection is None


async def test_reconnects_and_asks_for_a_resync(instances: tuple[Hub, Hub]) -> None:
    sender, receiver = instances
    async with receiver.subscribe({"orders"}) as subscriber:
        pid = receiver.relay.connection.get_server_pid()
        async with test_engine.begin() as conn:
            await conn.execute(select(func.pg_terminate_backend(pid)))

        assert await next_event(subscriber) is RESYNC
        assert receiver.relay.connection.get_server_pid() != pid

        event = {"event": "order.updated", "topic": "orders", "data": {"id": 3}, "at": "now"}
        await sender.publish(event)
        assert await next_event(subscriber) == event
