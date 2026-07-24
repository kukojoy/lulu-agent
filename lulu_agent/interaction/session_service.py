from pathlib import Path
from typing import Any

from lulu_agent.context.manager import ContextManager
from lulu_agent.storage.session_store import SessionStore


class SessionInteractionService:
    def __init__(self, session_store: SessionStore | None = None):
        self.session_store = session_store or SessionStore()

    def create_session(self, cwd: Path | str | None = None, title: str = "") -> dict[str, Any]:
        return self.session_store.create_session(cwd=cwd, title=title)

    def resume_session(self, session_id: str) -> str:
        self.session_store.validate_session(session_id)
        return session_id

    def list_sessions(self, limit: int | None = 20) -> list[dict[str, Any]]:
        return self.session_store.list_sessions(limit=limit)

    def inspect_session(self, session_id: str) -> dict[str, Any]:
        return self.session_store.inspect_session(session_id)

    def inspect_context(self, session_id: str) -> dict[str, Any]:
        self.session_store.validate_session(session_id)
        manager = ContextManager(session_store=self.session_store, session_id=session_id)
        inspection = manager.inspect_context(self.session_store.load_messages(session_id))
        return inspection.to_dict()
