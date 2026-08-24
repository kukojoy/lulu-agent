from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import Any

from lulu_agent.core.agent_loop import AgentLoop
from lulu_agent.interaction import (
    MemoryInteractionService,
    ModelInteractionService,
    SessionInteractionService,
    SkillInteractionService,
    TaskInteractionService,
    TraceInteractionService,
)
from lulu_agent.llm.client import LLMClient
from lulu_agent.llm.response import LLMClientConfig
from lulu_agent.runtime.errors import (
    ERROR_INVALID_ARGUMENTS,
    ERROR_SESSION_NOT_ACTIVE,
    ERROR_SESSION_RUNNING,
    ErrorType,
    LuluError,
)
from lulu_agent.safety.approval import use_approval_provider
from lulu_agent.server.agent_factory import build_server_agent
from lulu_agent.server.approval import ServerApprovalProvider
from lulu_agent.server.events import EventHub
from lulu_agent.skills.store import SkillStore
from lulu_agent.memory.store import MemoryStore
from lulu_agent.storage.session_store import SessionStore, SessionStoreError
from lulu_agent.storage.trace_store import TraceStore


class ServerRunnerError(LuluError):
    def __init__(self, error_message: str, error_type: ErrorType):
        super().__init__(error_message, error_type)


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
        self.memory_service = MemoryInteractionService(self.memory_store)
        self.model_service = ModelInteractionService()
        self.session_service = SessionInteractionService(self.session_store)
        self.skill_service = SkillInteractionService(self.skill_store)
        self.task_service = TaskInteractionService(self.session_store)
        self.trace_service = TraceInteractionService(self.trace_store)
        self._agents: dict[str, AgentLoop] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._approval_providers: dict[str, ServerApprovalProvider] = {}
        self._session_model_configs: dict[str, LLMClientConfig] = {}
        self._lock = threading.Lock()

    def create_session(self, workspace: str | Path | None = None) -> dict[str, Any]:
        return self.session_service.create_session(workspace=workspace)

    def browse_workspace(self, path: str | Path | None = None) -> dict[str, Any]:
        root = Path(path or Path.cwd()).expanduser().resolve()
        if not root.exists():
            raise SessionStoreError(
                f"Workspace not found: {root}",
                ERROR_INVALID_ARGUMENTS,
            )
        if not root.is_dir():
            raise SessionStoreError(
                f"Workspace is not a directory: {root}",
                ERROR_INVALID_ARGUMENTS,
            )

        entries = []
        for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
            if child.is_dir():
                entries.append(
                    {
                        "name": child.name,
                        "path": str(child.resolve()),
                        "kind": "directory",
                    }
                )
        parent = root.parent if root.parent != root else None
        return {
            "path": str(root),
            "parent": str(parent.resolve()) if parent is not None else None,
            "entries": entries,
        }

    def list_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        sessions = self.session_service.list_sessions(limit=limit)
        with self._lock:
            active_session_ids = set(self._agents)
        return [
            {
                **session,
                "active": not session.get("locked")
                and session.get("session_id") in active_session_ids,
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
            turn_runtime = getattr(agent, "turn_runtime", None)
            if turn_runtime is not None:
                active_turn_id = turn_runtime.turn_id
                status = getattr(turn_runtime.status, "value", turn_runtime.status)
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
        return self.model_service.get_model_config()

    def get_session_model_config(self, session_id: str) -> dict[str, Any]:
        self.session_service.resume_session(session_id)
        with self._lock:
            agent = self._agents.get(session_id)
            pending_config = self._session_model_configs.get(session_id)
        if agent is None:
            if pending_config is not None:
                return self.model_service.config_view(pending_config)
            return self.get_model_config()
        return agent.llm_client.get_model_config().to_dict()

    def list_model_providers(self) -> list[dict[str, Any]]:
        return self.model_service.list_model_providers()

    def list_provider_models(self, provider: str) -> dict[str, Any]:
        return self.model_service.list_provider_models(provider)

    def update_session_model(self, session_id: str, provider: str, model: str) -> dict[str, Any]:
        self.session_service.resume_session(session_id)
        lock = self._lock_for_session(session_id)
        if not lock.acquire(blocking=False):
            raise ServerRunnerError("session is already running.", ERROR_SESSION_RUNNING)
        try:
            self.session_service.resume_session(session_id)
            with self._lock:
                agent = self._agents.get(session_id)
            next_config = self.model_service.build_model_config(provider, model)
            if agent is None:
                with self._lock:
                    self._session_model_configs[session_id] = next_config
                return self.model_service.config_view(next_config)
            llm_client = LLMClient(next_config)
            agent.set_llm_client(llm_client)
            with self._lock:
                self._session_model_configs[session_id] = next_config
            return llm_client.get_model_config().to_dict()
        finally:
            lock.release()

    def delete_session(self, session_id: str) -> dict[str, Any]:
        lock = self._lock_for_session(session_id)
        if not lock.acquire(blocking=False):
            raise ServerRunnerError("session is already running.", ERROR_SESSION_RUNNING)
        try:
            metadata = self.session_service.delete_session(session_id)
            self.trace_store.delete_session_trace(session_id)
            with self._lock:
                self._agents.pop(session_id, None)
                self._approval_providers.pop(session_id, None)
                self._session_model_configs.pop(session_id, None)
            return metadata
        finally:
            lock.release()

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
        return self.memory_service.get_memory()

    def list_skills(self) -> dict[str, Any]:
        return self.skill_service.list_skills()

    def read_skill(self, name: str) -> dict[str, Any]:
        return self.skill_service.read_skill(name)

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
            raise ServerRunnerError("session is already running.", ERROR_SESSION_RUNNING)
        try:
            self.session_service.resume_session(session_id)
            with self._lock:
                agent = self._agents.get(session_id)
            if agent is None:
                raise ServerRunnerError(
                    "session agent is not loaded.",
                    ERROR_SESSION_NOT_ACTIVE,
                )
            return agent.reload_mcp_tools()
        finally:
            lock.release()

    def run_message(self, session_id: str, content: str) -> dict[str, Any]:
        if not isinstance(content, str) or not content.strip():
            raise ValueError("message content must be a non-empty string.")
        self.session_service.resume_session(session_id)
        lock = self._lock_for_session(session_id)
        if not lock.acquire(blocking=False):
            raise ServerRunnerError("session is already running.", ERROR_SESSION_RUNNING)
        try:
            self.session_service.resume_session(session_id)
            agent = self._agent_for_session(session_id)
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
        with self._lock:
            agent = self._agents.get(session_id)
            model_config = self._session_model_configs.get(session_id)
        if agent is not None:
            return agent

        if model_config is None:
            model_config = self.model_service.build_model_config()
        agent = build_server_agent(
            session_store=self.session_store,
            trace_store=self.trace_store,
            memory_store=self.memory_store,
            skill_store=self.skill_store,
            event_hub=self.event_hub,
            session_id=session_id,
            model_config=model_config,
        )

        with self._lock:
            existing_agent = self._agents.get(session_id)
            if existing_agent is not None:
                return existing_agent
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
