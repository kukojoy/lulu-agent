from typing import Any

from lulu_agent.storage.session_store import SessionStore


class TaskInteractionService:
    def __init__(self, session_store: SessionStore | None = None):
        self.session_store = session_store or SessionStore()

    def get_task_state(self, session_id: str) -> dict[str, Any] | None:
        self.session_store.validate_session(session_id)
        task_state = self.session_store.load_latest_task_state(session_id)
        return task_state.to_dict() if task_state else None
