from pathlib import Path
from typing import Any

from lulu_agent.context.manager import ContextManager
from lulu_agent.memory.store import MemoryStore
from lulu_agent.runtime.errors import ERROR_INVALID_ARGUMENTS
from lulu_agent.runtime.workspace import get_workspace_status, resolve_workspace
from lulu_agent.storage.session_store import (
    SessionStore,
    SessionStoreError,
    SessionWorkspaceUnavailableError,
)


class SessionInteractionService:
    def __init__(self, session_store: SessionStore | None = None):
        self.session_store = session_store or SessionStore()

    def create_session(self, workspace: Path | str | None = None, title: str = "") -> dict[str, Any]:
        try:
            cwd = resolve_workspace(workspace)
        except ValueError as exc:
            raise SessionStoreError(str(exc), ERROR_INVALID_ARGUMENTS) from exc
        return self.session_store.create_session(cwd=cwd, title=title)

    def resume_session(self, session_id: str) -> str:
        self.require_available_session(session_id)
        return session_id

    def get_session_metadata(self, session_id: str) -> dict[str, Any]:
        return self.require_available_session(session_id)

    def require_available_session(self, session_id: str) -> dict[str, Any]:
        self.session_store.validate_session(session_id)
        metadata = self.session_store.get_session_metadata(session_id)
        status = get_workspace_status(metadata.get("cwd"))
        if not status.available:
            raise SessionWorkspaceUnavailableError(
                status.message or "Session workspace is unavailable."
            )
        return metadata

    def load_messages(self, session_id: str) -> list[dict[str, Any]]:
        self.require_available_session(session_id)
        return [message.to_dict() for message in self.session_store.load_messages(session_id)]

    def list_sessions(self, limit: int | None = 20) -> list[dict[str, Any]]:
        sessions = self.session_store.list_sessions(limit=limit)
        result = []
        for session in sessions:
            status = get_workspace_status(session.get("cwd"))
            result.append(
                {
                    **session,
                    "locked": not status.available,
                    "lock_message": status.message,
                }
            )
        return result

    def delete_session(self, session_id: str) -> dict[str, Any]:
        return self.session_store.delete_session(session_id)

    def inspect_session(self, session_id: str) -> dict[str, Any]:
        self.require_available_session(session_id)
        return self.session_store.inspect_session(session_id)

    def inspect_context(self, session_id: str) -> dict[str, Any]:
        metadata = self.require_available_session(session_id)
        cwd = Path(metadata["cwd"]).expanduser().resolve()
        manager = ContextManager(
            memory_store=MemoryStore(project_path=cwd / "AGENTS.md"),
            session_store=self.session_store,
            session_id=session_id,
        )
        inspection = manager.inspect_context(self.session_store.load_messages(session_id))
        return inspection.to_dict()
