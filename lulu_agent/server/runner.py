from __future__ import annotations

import queue
import threading
from dataclasses import asdict
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
from lulu_agent.llm import providers as model_providers
from lulu_agent.llm.response import LLMClientConfig
from lulu_agent.safety.approval import ApprovalProvider, ApprovalRequest, use_approval_provider
from lulu_agent.runtime.event_sinks import CompositeEventSink, PersistentEventSink
from lulu_agent.runtime.events import EVENT_APPROVAL_REQUEST, EventPayloadBuilder, RuntimeEvent
from lulu_agent.server.events import EventHub, HubEventSink
from lulu_agent.memory.review import MemoryReviewer
from lulu_agent.skills.store import SkillStore
from lulu_agent.skills.review import SkillReviewer
from lulu_agent.memory.store import MemoryStore
from lulu_agent.storage.session_store import SessionStore
from lulu_agent.storage.trace_store import TraceStore


class ServerRunnerError(RuntimeError):
    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


class ServerApprovalProvider(ApprovalProvider):
    def __init__(self, event_hub: EventHub, session_id: str, timeout_seconds: int = 300):
        self.event_hub = event_hub
        self.session_id = session_id
        self.timeout_seconds = timeout_seconds
        self._lock = threading.Lock()
        self._pending: dict[str, queue.Queue[bool]] = {}
        self._requests: dict[str, ApprovalRequest] = {}

    def request_approval(self, request: ApprovalRequest) -> bool:
        response_queue: queue.Queue[bool] = queue.Queue(maxsize=1)
        with self._lock:
            self._pending[request.request_id] = response_queue
            self._requests[request.request_id] = request

        self.event_hub.publish(
            self.session_id,
            RuntimeEvent(
                type=EVENT_APPROVAL_REQUEST,
                turn_id="",
                payload=EventPayloadBuilder.build_approval_request_payload(
                    request_id=request.request_id,
                    category=request.category,
                    reason=request.reason,
                    subject=request.subject,
                ),
            ),
        )

        try:
            return response_queue.get(timeout=self.timeout_seconds)
        except queue.Empty:
            return False
        finally:
            with self._lock:
                self._pending.pop(request.request_id, None)
                self._requests.pop(request.request_id, None)

    def resolve(self, request_id: str, approved: bool) -> bool:
        with self._lock:
            response_queue = self._pending.get(request_id)
        if response_queue is None:
            return False
        try:
            response_queue.put_nowait(bool(approved))
        except queue.Full:
            return False
        return True

    def cancel_pending(self) -> int:
        with self._lock:
            queues = list(self._pending.values())
        cancelled = 0
        for response_queue in queues:
            try:
                response_queue.put_nowait(False)
                cancelled += 1
            except queue.Full:
                continue
        return cancelled

    def pending_request(self) -> dict[str, str] | None:
        with self._lock:
            request = next(iter(self._requests.values()), None)
        if request is None:
            return None
        return {
            "request_id": request.request_id,
            "category": request.category,
            "reason": request.reason,
            "subject": request.subject,
        }


class ServerRunner:
    def __init__(
        self,
        session_store: SessionStore | None = None,
        trace_store: TraceStore | None = None,
        memory_store: MemoryStore | None = None,
        skill_store: SkillStore | None = None,
        event_hub: EventHub | None = None,
    ):
        self.session_store = session_store or SessionStore()
        self.trace_store = trace_store or TraceStore()
        self.memory_store = memory_store or MemoryStore()
        self.skill_store = skill_store or SkillStore()
        self.event_hub = event_hub or EventHub()
        self.session_service = SessionInteractionService(self.session_store)
        self.task_service = TaskInteractionService(self.session_store)
        self.trace_service = TraceInteractionService(self.trace_store)
        self._agents: dict[str, AgentLoop] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._approval_providers: dict[str, ServerApprovalProvider] = {}
        self._session_model_configs: dict[str, LLMClientConfig] = {}
        self._lock = threading.Lock()

    def create_session(self) -> dict[str, Any]:
        return self.session_service.create_session(cwd=Path.cwd())

    def list_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        sessions = self.session_service.list_sessions(limit=limit)
        with self._lock:
            active_session_ids = set(self._agents)
        return [
            {
                **session,
                "active": session.get("session_id") in active_session_ids,
            }
            for session in sessions
        ]

    def resume_session(self, session_id: str) -> str:
        return self.session_service.resume_session(session_id)

    def get_runtime_state(self, session_id: str) -> dict[str, Any]:
        self.session_service.resume_session(session_id)
        lock = self._lock_for_session(session_id)
        with self._lock:
            agent = self._agents.get(session_id)
            provider = self._approval_providers.get(session_id)
        notices = []
        active_turn_id = None
        status = None
        if agent is not None:
            notices = [
                f"MCP warning [{issue.source}]: {issue.issue_message}"
                for issue in agent.tool_registry.get_issues()
            ]
            current_turn = getattr(agent, "current_turn", None)
            if current_turn is not None:
                active_turn_id = current_turn.turn_id
                status = getattr(current_turn.status, "value", current_turn.status)
        return {
            "session_id": session_id,
            "active": agent is not None,
            "running": lock.locked(),
            "connected": self.event_hub.subscriber_count(session_id) > 0,
            "active_turn_id": active_turn_id,
            "status": status,
            "pending_approval": provider.pending_request() if provider is not None else None,
            "notices": notices,
        }

    def get_model_config(self) -> dict[str, Any]:
        return LLMClient(model_providers.build_model_config()).get_model_config().to_dict()

    def get_session_model_config(self, session_id: str) -> dict[str, Any]:
        self.session_service.resume_session(session_id)
        with self._lock:
            agent = self._agents.get(session_id)
            pending_config = self._session_model_configs.get(session_id)
        if agent is None:
            if pending_config is not None:
                return LLMClient(pending_config).get_model_config().to_dict()
            return self.get_model_config()
        return agent.llm_client.get_model_config().to_dict()

    def list_model_providers(self) -> list[dict[str, Any]]:
        return [provider.to_dict() for provider in model_providers.list_model_providers()]

    def list_provider_models(self, provider: str) -> dict[str, Any]:
        return model_providers.discover_provider_models(provider).to_dict()

    def update_session_model(self, session_id: str, provider: str, model: str) -> dict[str, Any]:
        self.session_service.resume_session(session_id)
        lock = self._lock_for_session(session_id)
        if not lock.acquire(blocking=False):
            raise ServerRunnerError("session is already running.", code="session_running")
        try:
            with self._lock:
                agent = self._agents.get(session_id)
            next_config = model_providers.build_model_config(provider, model)
            if agent is None:
                with self._lock:
                    self._session_model_configs[session_id] = next_config
                return LLMClient(next_config).get_model_config().to_dict()
            llm_client = LLMClient(next_config)
            agent.set_llm_client(llm_client)
            with self._lock:
                self._session_model_configs[session_id] = next_config
            return llm_client.get_model_config().to_dict()
        finally:
            lock.release()

    def delete_session(self, session_id: str) -> dict[str, Any]:
        metadata = self.session_service.delete_session(session_id)
        self.trace_store.delete_session_trace(session_id)
        with self._lock:
            self._agents.pop(session_id, None)
            self._locks.pop(session_id, None)
            self._approval_providers.pop(session_id, None)
            self._session_model_configs.pop(session_id, None)
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

    def get_trace_turns(self, session_id: str) -> list[dict[str, Any]]:
        self.session_service.resume_session(session_id)
        return self.trace_service.build_turns(session_id)

    def get_memory(self) -> dict[str, Any]:
        return self.memory_store.read()

    def list_skills(self) -> dict[str, Any]:
        result = self.skill_store.list_skills()
        return {
            "root": result.root,
            "skills": [asdict(skill) for skill in result.skills],
            "load_issues": [asdict(issue) for issue in result.load_issues],
        }

    def read_skill(self, name: str) -> dict[str, Any]:
        result = self.skill_store.read_skill(name)
        return result.to_dict(("name", "description", "path", "directory", "content"))

    def list_mcp_tools(self, session_id: str) -> dict[str, Any]:
        self.session_service.resume_session(session_id)
        with self._lock:
            agent = self._agents.get(session_id)
        if agent is None:
            return {"servers": []}
        return agent.tool_registry.list_mcp_tools()

    def reload_mcp_tools(self, session_id: str) -> dict[str, Any]:
        self.session_service.resume_session(session_id)
        lock = self._lock_for_session(session_id)
        if not lock.acquire(blocking=False):
            raise ServerRunnerError("session is already running.", code="session_running")
        try:
            with self._lock:
                agent = self._agents.get(session_id)
            if agent is None:
                raise ServerRunnerError("session agent is not loaded.", code="session_not_active")
            return agent.reload_mcp_tools()
        finally:
            lock.release()

    def run_message(self, session_id: str, content: str) -> dict[str, Any]:
        if not isinstance(content, str) or not content.strip():
            raise ValueError("message content must be a non-empty string.")
        agent = self._agent_for_session(session_id)
        lock = self._lock_for_session(session_id)
        if not lock.acquire(blocking=False):
            raise ServerRunnerError("session is already running.", code="session_running")
        try:
            with use_approval_provider(self._approval_provider_for_session(session_id)):
                response = agent.run(content.strip())
        finally:
            lock.release()
        return {
            "session_id": session_id,
            "response": response,
        }

    def interrupt_session(self, session_id: str) -> bool:
        self.session_service.resume_session(session_id)
        with self._lock:
            agent = self._agents.get(session_id)
            provider = self._approval_providers.get(session_id)
        if agent is None:
            return False
        interrupted = agent.request_interrupt()
        if provider is not None:
            provider.cancel_pending()
        return interrupted

    def resolve_approval(self, session_id: str, request_id: str, approved: bool) -> bool:
        self.session_service.resume_session(session_id)
        return self._approval_provider_for_session(session_id).resolve(request_id, approved)

    def _agent_for_session(self, session_id: str) -> AgentLoop:
        self.session_service.resume_session(session_id)
        with self._lock:
            agent = self._agents.get(session_id)
            if agent is None:
                model_config = self._session_model_configs.get(session_id)
                if model_config is None:
                    model_config = model_providers.build_model_config()
                agent = AgentLoop(
                    session_store=self.session_store,
                    session_id=session_id,
                    llm_client=LLMClient(model_config),
                    event_sink=CompositeEventSink(
                        [
                            HubEventSink(self.event_hub, session_id),
                            PersistentEventSink(self.trace_store, session_id),
                        ]
                    ),
                    memory_reviewer=MemoryReviewer(memory_store=self.memory_store),
                    skill_reviewer=SkillReviewer(skill_store=self.skill_store),
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

    def _approval_provider_for_session(self, session_id: str) -> ServerApprovalProvider:
        with self._lock:
            provider = self._approval_providers.get(session_id)
            if provider is None:
                provider = ServerApprovalProvider(self.event_hub, session_id)
                self._approval_providers[session_id] = provider
            return provider
