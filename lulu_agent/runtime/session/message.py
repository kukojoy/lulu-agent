from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lulu_agent.runtime.session.model import SessionRuntimeModel
from lulu_agent.storage.session_record import SessionRecordType


@dataclass(frozen=True)
class Message(SessionRuntimeModel):
    type = SessionRecordType.MESSAGE

    role: str
    content: Any = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    turn_id: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Message":
        tool_calls = data.get("tool_calls")
        tool_call_id = data.get("tool_call_id")
        turn_id = data.get("turn_id")
        return cls(
            role=str(data.get("role") or ""),
            content=data.get("content"),
            tool_calls=list(tool_calls) if isinstance(tool_calls, list) else [],
            tool_call_id=tool_call_id if isinstance(tool_call_id, str) and tool_call_id else None,
            turn_id=turn_id if isinstance(turn_id, str) and turn_id else None,
        )

    def to_dict(self) -> dict[str, Any]:
        data = self.for_request()
        if self.turn_id:
            data["turn_id"] = self.turn_id
        return data

    def for_request(self) -> dict[str, Any]:
        data = {
            "role": self.role,
            "content": self.content,
        }
        if self.tool_calls:
            data["tool_calls"] = list(self.tool_calls)
        if self.tool_call_id:
            data["tool_call_id"] = self.tool_call_id
        return data
