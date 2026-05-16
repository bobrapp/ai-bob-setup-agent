"""Event bus — SQLite-backed pub/sub for agent communication.

Agents subscribe to event patterns. The bus polls for unprocessed events
and dispatches them to matching subscribers.
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
from typing import Any, Callable, Awaitable

from src.personal_foundation.v2.state import StateStore

log = logging.getLogger(__name__)

EventHandler = Callable[[dict], Awaitable[None]]


class EventBus:
    """SQLite-backed event bus with pattern-based subscriptions."""

    def __init__(self, store: StateStore, poll_interval: float = 1.0) -> None:
        self.store = store
        self.poll_interval = poll_interval
        self._subscribers: list[tuple[str, str, EventHandler]] = []  # (pattern, agent_name, handler)
        self._running = False

    def subscribe(self, pattern: str, agent_name: str, handler: EventHandler) -> None:
        """Subscribe to events matching a pattern (supports * wildcards).

        Examples:
            bus.subscribe("email.*", "email_classifier", handle_email)
            bus.subscribe("member.joined", "welcomer", handle_join)
            bus.subscribe("schedule.daily_0700", "research_scanner", handle_scan)
        """
        self._subscribers.append((pattern, agent_name, handler))
        log.info("EventBus: %s subscribed to '%s'", agent_name, pattern)

    def emit(self, event_type: str, payload: dict) -> int:
        """Emit an event. Persists to SQLite. Returns event ID."""
        event_id = self.store.emit_event(event_type, payload)
        log.debug("EventBus: emitted %s (id=%d)", event_type, event_id)
        return event_id

    async def start(self) -> None:
        """Start the event processing loop."""
        self._running = True
        log.info("EventBus: started (poll_interval=%.1fs, %d subscribers)",
                 self.poll_interval, len(self._subscribers))

        while self._running:
            await self._process_pending()
            await asyncio.sleep(self.poll_interval)

    def stop(self) -> None:
        """Stop the event processing loop."""
        self._running = False
        log.info("EventBus: stopped")

    async def _process_pending(self) -> None:
        """Process all unprocessed events."""
        events = self.store.get_unprocessed_events()

        for event in events:
            event_type = event["event_type"]
            payload = event.get("payload_json", "{}")
            if isinstance(payload, str):
                import json
                payload = json.loads(payload)

            matched = False
            for pattern, agent_name, handler in self._subscribers:
                if fnmatch.fnmatch(event_type, pattern):
                    matched = True
                    try:
                        await handler({"event_type": event_type, "payload": payload, "event_id": event["id"]})
                        self.store.mark_event_processed(event["id"], agent_name)
                    except Exception as exc:
                        log.error("EventBus: handler %s failed for %s: %s",
                                  agent_name, event_type, exc)
                        # Don't mark as processed — will retry next cycle
                    break  # First matching subscriber handles it

            if not matched:
                # No subscriber — mark as processed to avoid infinite retry
                self.store.mark_event_processed(event["id"], "no_subscriber")
