from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

TurnStatus = Literal[
    "running",
    "requesting_model",
    "streaming_assistant",
    "running_tool",
    "finalizing",
    "completed",
    "failed",
    "interrupted",
]

TurnExitReason = Literal[
    "assistant_final",
    "max_turns_exhausted",
    "model_error",
    "tool_error",
    "stream_error",
    "approval_denied",
    "user_interrupted",
    "unknown_error",
]


@dataclass(frozen=True)
class TurnRecord:
    turn_id: str
    status: TurnStatus
    exit_reason: TurnExitReason | None
    error: str | None
    model_calls: int
    tool_calls: int
    final_response: str
    model_usage: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TurnRecord":
        return cls(
            turn_id=data["turn_id"],
            status=data["status"],
            exit_reason=data["exit_reason"],
            error=data["error"],
            model_calls=data["model_calls"],
            tool_calls=data["tool_calls"],
            final_response=data["final_response"],
            model_usage=data["model_usage"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "status": self.status,
            "exit_reason": self.exit_reason,
            "error": self.error,
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
            "model_usage": list(self.model_usage),
            "final_response": self.final_response,
        }

    def latest_prompt_tokens(self) -> int | None:
        for usage in reversed(self.model_usage):
            prompt_tokens = usage.get("prompt_tokens")
            if isinstance(prompt_tokens, int):
                return prompt_tokens
        return None


@dataclass
class TurnRuntime:
    turn_id: str
    status: TurnStatus = "running"
    exit_reason: TurnExitReason | None = None
    error: str | None = None
    current_tool: str | None = None
    model_calls: int = 0
    tool_calls: int = 0
    model_usage: list[dict[str, Any]] = field(default_factory=list)

    def set_status(self, status: TurnStatus) -> None:
        self.status = status

    def start_model_request(self) -> None:
        self.model_calls += 1
        self.status = "requesting_model"

    def record_model_usage(self, usage: dict[str, Any] | None) -> None:
        if not usage:
            return
        usage_record = {"request_index": self.model_calls, **usage}
        self.model_usage.append(usage_record)

    def start_streaming(self) -> None:
        self.status = "streaming_assistant"

    def start_tool(self, tool_name: str) -> None:
        self.tool_calls += 1
        self.current_tool = tool_name
        self.status = "running_tool"

    def finish_tool(self) -> None:
        self.current_tool = None
        self.status = "running"

    def complete(self, reason: TurnExitReason = "assistant_final") -> None:
        self.status = "completed"
        self.exit_reason = reason
        self.error = None

    def fail(self, reason: TurnExitReason, error: str) -> None:
        self.status = "failed"
        self.exit_reason = reason
        self.error = error

    def interrupt(self, error: str = "Interrupted by user.", reason: TurnExitReason = "user_interrupted") -> None:
        self.status = "interrupted"
        self.exit_reason = reason
        self.error = error

    def to_record(self, final_response: str = "") -> TurnRecord:
        if self.exit_reason is None:
            if self.status == "completed":
                self.exit_reason = "assistant_final"
            elif self.status == "interrupted":
                self.exit_reason = "user_interrupted"
            elif self.status == "failed":
                self.exit_reason = "unknown_error"
            else:
                self.status = "failed"
                self.exit_reason = "unknown_error"
                self.error = self.error or "Turn ended without an exit reason."

        return TurnRecord(
            turn_id=self.turn_id,
            status=self.status,
            exit_reason=self.exit_reason,
            error=self.error,
            model_calls=self.model_calls,
            tool_calls=self.tool_calls,
            model_usage=list(self.model_usage),
            final_response=final_response,
        )
