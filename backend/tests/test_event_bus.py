"""
Tests for the EventBus — subscribe, publish, sync and async handlers,
handler failure isolation.
"""

import pytest
from app.events.event_bus import EventBus
from app.events.user_events import UserRegisteredEvent, UserLoggedInEvent


async def test_handler_is_called_on_publish():
    bus = EventBus()
    calls = []

    def handler(event):
        calls.append(event)

    bus.subscribe(UserRegisteredEvent, handler)
    await bus.publish(UserRegisteredEvent(user_id="u1", email="a@b.com"))

    assert len(calls) == 1
    assert calls[0].email == "a@b.com"


async def test_async_handler_is_awaited():
    bus = EventBus()
    results = []

    async def async_handler(event):
        results.append(event.user_id)

    bus.subscribe(UserRegisteredEvent, async_handler)
    await bus.publish(UserRegisteredEvent(user_id="u42", email="x@y.com"))

    assert results == ["u42"]


async def test_multiple_handlers_all_called():
    bus = EventBus()
    log = []

    bus.subscribe(UserRegisteredEvent, lambda e: log.append("handler_1"))
    bus.subscribe(UserRegisteredEvent, lambda e: log.append("handler_2"))

    await bus.publish(UserRegisteredEvent(user_id="u1", email="x@y.com"))

    assert log == ["handler_1", "handler_2"]


async def test_unrelated_event_not_dispatched():
    bus = EventBus()
    calls = []

    bus.subscribe(UserLoggedInEvent, lambda e: calls.append(e))

    # publish a different event type
    await bus.publish(UserRegisteredEvent(user_id="u1", email="x@y.com"))

    assert calls == []


async def test_failing_handler_does_not_stop_other_handlers():
    """A handler that raises must not crash the bus or skip subsequent handlers."""
    bus = EventBus()
    reached = []

    def bad_handler(event):
        raise RuntimeError("something went wrong in this handler")

    def good_handler(event):
        reached.append("good")

    bus.subscribe(UserRegisteredEvent, bad_handler)
    bus.subscribe(UserRegisteredEvent, good_handler)

    # should not raise
    await bus.publish(UserRegisteredEvent(user_id="u1", email="x@y.com"))

    assert reached == ["good"]


async def test_no_handlers_registered_publish_does_nothing():
    bus = EventBus()
    # should not raise even with zero subscribers
    await bus.publish(UserRegisteredEvent(user_id="u1", email="x@y.com"))
