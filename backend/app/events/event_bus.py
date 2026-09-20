from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Callable, Type, Any

logger = logging.getLogger(__name__)


class EventBus:
    """
    Lightweight in-process async event bus.

    Usage:
        bus = EventBus()
        bus.subscribe(UserRegisteredEvent, my_handler)
        await bus.publish(UserRegisteredEvent(user_id="...", email="..."))
    """

    def __init__(self) -> None:
        self._handlers: dict[Type, list[Callable]] = defaultdict(list)

    def subscribe(self, event_type: Type, handler: Callable) -> None:
        self._handlers[event_type].append(handler)

    async def publish(self, event: Any) -> None:
        handlers = self._handlers.get(type(event), [])
        for handler in handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception(
                    "Event handler %s failed for event %s",
                    handler.__name__,
                    type(event).__name__,
                )


# Application-wide singleton
event_bus = EventBus()
