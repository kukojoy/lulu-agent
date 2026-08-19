from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from lulu_agent.runtime.compression import Compression
from lulu_agent.runtime.message import Message
from lulu_agent.runtime.task_state import TaskState
from lulu_agent.runtime.turn import Turn


class SessionRecordType(StrEnum):
    MESSAGE = "message"
    TURN = "turn"
    COMPRESSION = "compression"
    TASK_STATE = "task_state"


@dataclass(frozen=True)
class SessionRecord:
    type: SessionRecordType
    session_id: str
    created_at: str
    data: dict[str, Any]

    @classmethod
    def from_message(
        cls,
        session_id: str,
        created_at: str,
        message: Message,
    ) -> "SessionRecord":
        return cls(
            type=SessionRecordType.MESSAGE,
            session_id=session_id,
            created_at=created_at,
            data=message.to_dict(),
        )

    @classmethod
    def from_turn(
        cls,
        session_id: str,
        created_at: str,
        turn: Turn,
    ) -> "SessionRecord":
        return cls(
            type=SessionRecordType.TURN,
            session_id=session_id,
            created_at=created_at,
            data=turn.to_dict(),
        )

    @classmethod
    def from_compression(
        cls,
        session_id: str,
        created_at: str,
        compression: Compression,
    ) -> "SessionRecord":
        return cls(
            type=SessionRecordType.COMPRESSION,
            session_id=session_id,
            created_at=created_at,
            data=compression.to_dict(),
        )

    @classmethod
    def from_task_state(
        cls,
        session_id: str,
        created_at: str,
        task_state: TaskState,
    ) -> "SessionRecord":
        return cls(
            type=SessionRecordType.TASK_STATE,
            session_id=session_id,
            created_at=created_at,
            data=task_state.to_dict(),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionRecord":
        return cls(
            type=SessionRecordType(data["type"]),
            session_id=data["session_id"],
            created_at=data["created_at"],
            data=data["data"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "data": dict(self.data),
        }

    def to_message(self) -> Message:
        self._ensure_type(SessionRecordType.MESSAGE)
        return Message.from_dict(self.data)

    def to_turn(self) -> Turn:
        self._ensure_type(SessionRecordType.TURN)
        return Turn.from_dict(self.data)

    def to_compression(self) -> Compression:
        self._ensure_type(SessionRecordType.COMPRESSION)
        return Compression.from_dict(self.data)

    def to_task_state(self) -> TaskState:
        self._ensure_type(SessionRecordType.TASK_STATE)
        return TaskState.from_dict(self.data)

    def _ensure_type(self, expected: SessionRecordType) -> None:
        if self.type != expected:
            raise ValueError(f"SessionRecord type must be {expected.value}, got {self.type.value}.")
