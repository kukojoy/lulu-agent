from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from lulu_agent.runtime.session.model import SessionRuntimeModel
from lulu_agent.storage.session_record import SessionRecordType


class CompressionScope(StrEnum):
    TURN_RANGE = "turn_range"
    FULL_HISTORY = "full_history"


@dataclass(frozen=True)
class Compression(SessionRuntimeModel):
    type = SessionRecordType.COMPRESSION

    compression_id: str
    scope: CompressionScope
    covered_turn_ids: list[str] = field(default_factory=list)
    summary: str = ""
    source_prompt_chars: int = 0
    summary_chars: int = 0
    summary_tokens: int | None = None
    model: str = ""
    reason: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Compression":
        return cls(
            compression_id=data["compression_id"],
            scope=CompressionScope(data["scope"]),
            covered_turn_ids=data["covered_turn_ids"],
            summary=data["summary"],
            source_prompt_chars=data["source_prompt_chars"],
            summary_chars=data["summary_chars"],
            summary_tokens=data["summary_tokens"],
            model=data["model"],
            reason=data["reason"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "compression_id": self.compression_id,
            "scope": self.scope.value,
            "covered_turn_ids": list(self.covered_turn_ids),
            "summary": self.summary,
            "source_prompt_chars": self.source_prompt_chars,
            "summary_chars": self.summary_chars,
            "summary_tokens": self.summary_tokens,
            "model": self.model,
            "reason": self.reason,
        }
