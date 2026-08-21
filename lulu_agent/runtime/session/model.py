from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Self

from lulu_agent.storage.session_record import SessionRecord, SessionRecordType
from lulu_agent.runtime.utils import get_local_time


class SessionRuntimeModel(ABC):
    type: SessionRecordType

    @classmethod
    @abstractmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        raise NotImplementedError

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        raise NotImplementedError

    @classmethod
    def from_record(cls, record: SessionRecord) -> Self:
        if record.type != cls.type:
            raise ValueError(
                f"SessionRecord type must be {cls.type.value}, got {record.type.value}."
            )
        return cls.from_dict(record.data)

    def to_record(self, session_id: str) -> SessionRecord:
        return SessionRecord(
            type=self.type,
            session_id=session_id,
            created_at=get_local_time().isoformat(),
            data=self.to_dict(),
        )
