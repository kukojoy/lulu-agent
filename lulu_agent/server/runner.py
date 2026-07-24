from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import Any

from lulu_agent.config import config
from lulu_agent.core.agent_loop import AgentLoop
from lulu_agent.interaction import (
    SessionInteractionService,
    TaskInteractionService,
    TraceInteractionService,
)
from lulu_agent.llm.client import LLMClient
from lulu_agent.runtime.event_sinks import CompositeEventSink, PersistentEventSink
from lulu_agent.server.events import EventHub, HubEventSink
from lulu_agent.storage.session_store import SessionStore
from lulu_agent.storage.trace_store import TraceStore


class ServerRunner:
    def __init__(
        self,
        session_store: SessionStore | None = None,
        trace_store: TraceStore | None = None,
        event_hub: EventHub | None = None,
    ):
        self.session_store = session_store or SessionStore()
        self.trace_store = trace_store or TraceStore()
        self.event_hub = event_hub or EventHub()
        self.session_service = SessionInteractionService(self.session_store)
        self.task_service = TaskInteractionService(self.session_store)
        self.trace_service = TraceInteractionService(self.trace_store)
        self._agents: dict[str, AgentLoop] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._lock = threading.Lock()

    def create_session(self) -> dict[str, Any]:
        return self.session_service.create_session(cwd=Path.cwd())

    def list_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.session_service.list_sessions(limit=limit)

    def resume_session(self, session_id: str) -> str:
        return self.session_service.resume_session(session_id)

    def delete_session(self, session_id: str) -> dict[str, Any]:
        metadata = self.session_service.delete_session(session_id)
        with self._lock:
            self._agents.pop(session_id, None)
            self._locks.pop(session_id, None)
        return metadata

    def subscribe_events(self, session_id: str) -> queue.Queue[dict[str, Any]]:
        return self.event_hub.subscribe(session_id)

    def unsubscribe_events(self, session_id: str, subscriber: queue.Queue[dict[str, Any]]) -> None:
        self.event_hub.unsubscribe(session_id, subscriber)

    def inspect_session(self, session_id: str) -> dict[str, Any]:
        return self.session_service.inspect_session(session_id)

    def load_messages(self, session_id: str) -> list[dict[str, Any]]:
        return self.session_service.load_messages(session_id)

    def inspect_context(self, session_id: str) -> dict[str, Any]:
        return self.session_service.inspect_context(session_id)

    def get_task_state(self, session_id: str) -> dict[str, Any] | None:
        return self.task_service.get_task_state(session_id)

    def get_trace_timeline(self, session_id: str, turn_id: str | None = None) -> list[dict[str, Any]]:
        self.session_service.resume_session(session_id)
        return self.trace_service.build_timeline(session_id, turn_id=turn_id)

    def run_message(self, session_id: str, content: str) -> dict[str, Any]:
        if not isinstance(content, str) or not content.strip():
            raise ValueError("message content must be a non-empty string.")
        agent = self._agent_for_session(session_id)
        lock = self._lock_for_session(session_id)
        with lock:
            response = agent.run(content.strip())
        return {
            "session_id": session_id,
            "response": response,
        }

    def _agent_for_session(self, session_id: str) -> AgentLoop:
        self.session_service.resume_session(session_id)
        with self._lock:
            agent = self._agents.get(session_id)
            if agent is None:
                agent = AgentLoop(
                    session_store=self.session_store,
                    session_id=session_id,
                    llm_client=LLMClient(config),
                    event_sink=CompositeEventSink(
                        [
                            HubEventSink(self.event_hub, session_id),
                            PersistentEventSink(self.trace_store, session_id),
                        ]
                    ),
                )
                self._agents[session_id] = agent
            return agent

    def _lock_for_session(self, session_id: str) -> threading.Lock:
        with self._lock:
            lock = self._locks.get(session_id)
            if lock is None:
                lock = threading.Lock()
                self._locks[session_id] = lock
            return lock
