from typing import Any

from lulu_agent.memory.store import MemoryStore


class MemoryInteractionService:
    def __init__(self, memory_store: MemoryStore | None = None):
        self.memory_store = memory_store or MemoryStore()

    def get_memory(self) -> dict[str, Any]:
        return self.memory_store.read()
