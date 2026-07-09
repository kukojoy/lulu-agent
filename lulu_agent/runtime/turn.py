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
    "user_interrupted",
    "unknown_error",
]


@dataclass
class TurnResult:
    turn_id: str
    status: TurnStatus
    exit_reason: TurnExitReason
    final_response: str
    error: str | None = None


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
        normalized: dict[str, Any] = {"request_index": self.model_calls}
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = usage.get(key)
            if isinstance(value, int):
                normalized[key] = value
        if len(normalized) > 1:
            self.model_usage.append(normalized)

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

    def interrupt(self, error: str = "Interrupted by user.") -> None:
        self.status = "interrupted"
        self.exit_reason = "user_interrupted"
        self.error = error

    def finalize(self, final_response: str = "") -> TurnResult:
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

        return TurnResult(
            turn_id=self.turn_id,
            status=self.status,
            exit_reason=self.exit_reason,
            final_response=final_response,
            error=self.error,
        )
