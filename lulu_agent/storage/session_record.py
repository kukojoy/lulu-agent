from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


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
    def from_dict(cls, raw_record: dict[str, Any]) -> "SessionRecord":
        record_type = raw_record.get("type")
        session_id = raw_record.get("session_id")
        created_at = raw_record.get("created_at")
        data = raw_record.get("data")

        if not isinstance(record_type, str) or not record_type:
            raise ValueError("session record type must be a non-empty string.")
        try:
            parsed_type = SessionRecordType(record_type)
        except ValueError:
            raise ValueError("session record type is invalid.")
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("session record session_id must be a non-empty string.")
        if not isinstance(created_at, str) or not created_at:
            raise ValueError("session record created_at must be a non-empty string.")
        if not isinstance(data, dict):
            raise ValueError(f"{parsed_type.value} must be an object.")
        return cls(
            type=parsed_type,
            session_id=session_id,
            created_at=created_at,
            data=data,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "data": dict(self.data),
        }
