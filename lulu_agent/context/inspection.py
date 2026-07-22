from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ContextBlockInspection:
    name: str
    chars: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "chars": self.chars,
        }


@dataclass(frozen=True)
class ContextInspection:
    message_count: int
    total_chars: int
    system_chars: int
    system_message: str = ""
    context_blocks: list[ContextBlockInspection] = field(default_factory=list)
    raw_turn_ids: list[str] = field(default_factory=list)
    compressed_turn_ids: list[str] = field(default_factory=list)
    compression_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_count": self.message_count,
            "total_chars": self.total_chars,
            "system_chars": self.system_chars,
            "system_message": self.system_message,
            "context_blocks": [block.to_dict() for block in self.context_blocks],
            "raw_turn_ids": list(self.raw_turn_ids),
            "compressed_turn_ids": list(self.compressed_turn_ids),
            "compression_ids": list(self.compression_ids),
        }
