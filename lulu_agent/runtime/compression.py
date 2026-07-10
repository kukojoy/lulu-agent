from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


CompressionScope = Literal["turn_range", "full_history"]


@dataclass(frozen=True)
class CompressionRecord:
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
    def from_dict(cls, data: dict[str, Any]) -> "CompressionRecord":
        return cls(
            compression_id=data["compression_id"],
            scope=data["scope"],
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
            "scope": self.scope,
            "covered_turn_ids": list(self.covered_turn_ids),
            "summary": self.summary,
            "source_prompt_chars": self.source_prompt_chars,
            "summary_chars": self.summary_chars,
            "summary_tokens": self.summary_tokens,
            "model": self.model,
            "reason": self.reason,
        }
