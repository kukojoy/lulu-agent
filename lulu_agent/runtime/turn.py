from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from lulu_agent.runtime.errors import ErrorType


class TurnStatus(StrEnum):
    RUNNING = "running"
    REQUESTING_MODEL = "requesting_model"
    STREAMING_ASSISTANT = "streaming_assistant"
    RUNNING_TOOL = "running_tool"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class TurnExitReason(StrEnum):
    ASSISTANT_FINAL = "assistant_final"
    MAX_TURNS_EXHAUSTED = "max_turns_exhausted"
    MODEL_ERROR = "model_error"
    TOOL_ERROR = "tool_error"
    STREAM_ERROR = "stream_error"
    APPROVAL_DENIED = "approval_denied"
    USER_INTERRUPTED = "user_interrupted"
    UNKNOWN_ERROR = "unknown_error"


@dataclass(frozen=True)
class TurnRecord:
    turn_id: str
    status: TurnStatus
    exit_reason: TurnExitReason
    error: str | None
    error_type: ErrorType | None
    model_calls: int
    tool_calls: int
    final_response: str
    model_usage: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TurnRecord":
        return cls(
            turn_id=data["turn_id"],
            status=TurnStatus(data["status"]),
            exit_reason=TurnExitReason(data["exit_reason"]),
            error=data["error"],
            error_type=ErrorType(data["error_type"]) if data.get("error_type") else None,
            model_calls=data["model_calls"],
            tool_calls=data["tool_calls"],
            final_response=data["final_response"],
            model_usage=data["model_usage"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "status": self.status.value,
            "exit_reason": self.exit_reason.value,
            "error": self.error,
            "error_type": self.error_type.value if self.error_type else None,
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
    status: TurnStatus = TurnStatus.RUNNING
    exit_reason: TurnExitReason | None = None
    error: str | None = None
    error_type: ErrorType | None = None
    current_tool: str | None = None
    model_calls: int = 0
    tool_calls: int = 0
    model_usage: list[dict[str, Any]] = field(default_factory=list)

    def set_status(self, status: TurnStatus) -> None:
        self.status = TurnStatus(status)

    def start_model_request(self) -> None:
        self.model_calls += 1
        self.status = TurnStatus.REQUESTING_MODEL

    def record_model_usage(self, usage: dict[str, Any] | None) -> None:
        if not usage:
            return
        usage_record = {"request_index": self.model_calls, **usage}
        self.model_usage.append(usage_record)

    def start_streaming(self) -> None:
        self.status = TurnStatus.STREAMING_ASSISTANT

    def start_tool(self, tool_name: str) -> None:
        self.tool_calls += 1
        self.current_tool = tool_name
        self.status = TurnStatus.RUNNING_TOOL

    def finish_tool(self) -> None:
        self.current_tool = None
        self.status = TurnStatus.RUNNING

    def complete(self, reason: TurnExitReason = TurnExitReason.ASSISTANT_FINAL) -> None:
        self.status = TurnStatus.COMPLETED
        self.exit_reason = TurnExitReason(reason)
        self.error = None
        self.error_type = None

    def fail(
        self,
        reason: TurnExitReason,
        error: str,
        error_type: ErrorType | None = None,
    ) -> None:
        self.status = TurnStatus.FAILED
        self.exit_reason = TurnExitReason(reason)
        self.error = error
        self.error_type = error_type

    def interrupt(
        self,
        error: str = "Interrupted by user.",
        reason: TurnExitReason = TurnExitReason.USER_INTERRUPTED,
        error_type: ErrorType | None = None,
    ) -> None:
        self.status = TurnStatus.INTERRUPTED
        self.exit_reason = TurnExitReason(reason)
        self.error = error
        self.error_type = error_type

    def to_record(self, final_response: str = "") -> TurnRecord:
        if self.exit_reason is None:
            if self.status == TurnStatus.COMPLETED:
                self.exit_reason = TurnExitReason.ASSISTANT_FINAL
            elif self.status == TurnStatus.INTERRUPTED:
                self.exit_reason = TurnExitReason.USER_INTERRUPTED
            elif self.status == TurnStatus.FAILED:
                self.exit_reason = TurnExitReason.UNKNOWN_ERROR
            else:
                self.status = TurnStatus.FAILED
                self.exit_reason = TurnExitReason.UNKNOWN_ERROR
                self.error = self.error or "Turn ended without an exit reason."

        return TurnRecord(
            turn_id=self.turn_id,
            status=self.status,
            exit_reason=self.exit_reason,
            error=self.error,
            error_type=self.error_type,
            model_calls=self.model_calls,
            tool_calls=self.tool_calls,
            model_usage=list(self.model_usage),
            final_response=final_response,
        )
