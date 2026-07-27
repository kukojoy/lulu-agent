from __future__ import annotations

import queue
import threading
from typing import Any

from lulu_agent.runtime.event_sinks import EventSink
from lulu_agent.runtime.events import RuntimeEvent


class EventHub:
    def __init__(self):
        self._lock = threading.Lock()
        self._subscribers: dict[str, list[queue.Queue[dict[str, Any]]]] = {}

    def publish(self, session_id: str, event: RuntimeEvent) -> None:
        payload = event.to_dict()
        with self._lock:
            subscribers = list(self._subscribers.get(session_id, []))
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(payload)
            except queue.Full:
                continue

    def subscribe(self, session_id: str, maxsize: int = 256) -> queue.Queue[dict[str, Any]]:
        subscriber: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=maxsize)
        with self._lock:
            self._subscribers.setdefault(session_id, []).append(subscriber)
        return subscriber

    def unsubscribe(self, session_id: str, subscriber: queue.Queue[dict[str, Any]]) -> None:
        with self._lock:
            subscribers = self._subscribers.get(session_id)
            if not subscribers:
                return
            if subscriber in subscribers:
                subscribers.remove(subscriber)
            if not subscribers:
                self._subscribers.pop(session_id, None)

    def subscriber_count(self, session_id: str) -> int:
        with self._lock:
            return len(self._subscribers.get(session_id, []))


class HubEventSink(EventSink):
    def __init__(self, hub: EventHub, session_id: str):
        self.hub = hub
        self.session_id = session_id

    def emit(self, event: RuntimeEvent) -> None:
        self.hub.publish(self.session_id, event)
