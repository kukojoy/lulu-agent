from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


EVENT_TURN_START = "turn_start"
EVENT_USER_MESSAGE = "user_message"
EVENT_MODEL_REQUEST = "model_request"
EVENT_ASSISTANT_DELTA = "assistant_delta"
EVENT_ASSISTANT_MESSAGE = "assistant_message"
EVENT_TOOL_CALL = "tool_call"
EVENT_TOOL_RESULT = "tool_result"
EVENT_ERROR = "error"
EVENT_TURN_END = "turn_end"

RuntimeEventType = Literal[
    "turn_start",
    "user_message",
    "model_request",
    "assistant_delta",
    "assistant_message",
    "tool_call",
    "tool_result",
    "error",
    "turn_end",
]


@dataclass(frozen=True)
class RuntimeEvent:
    """runtime event
    
    Attributes:
        type: 事件类型
        turn_id: 对话轮次 ID, agent loop 每次 run 都会生成一个新的 turn_id
        payload: 事件载荷 (主体数据)
        timestamp: 事件发生时间戳 (UTC 时间)
    """
    type: RuntimeEventType
    turn_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "turn_id": self.turn_id,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }
    

# === payload ===
@dataclass(frozen=True)
class TurnStartPayload:
    """Payload for turn_start

    当前 turn_start 事件没有额外字段. 保留空模型是为了让事件契约完整, 后续如果需要加入 cwd、session_id 等字段, 可以在这里扩展.
    """


@dataclass(frozen=True)
class UserMessagePayload:
    content: str


@dataclass(frozen=True)
class ModelRequestPayload:
    model: str
    stream: bool
    request_index: int
    message_count: int
    tool_count: int
    tool_names: list[str]
    total_message_chars: int


@dataclass(frozen=True)
class AssistantDeltaPayload:
    delta: str


@dataclass(frozen=True)
class AssistantMessagePayload:
    content: str
    tool_call_count: int
    final: bool
    streamed: bool
    usage: dict[str, Any] | None = None


@dataclass(frozen=True)
class ToolCallPayload:
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolResultPayload:
    tool_call_id: str
    tool_name: str
    ok: bool
    output: Any = None
    error: str | None = None


@dataclass(frozen=True)
class ErrorPayload:
    message: str


@dataclass(frozen=True)
class TurnEndPayload:
    status: str
    exit_reason: str
    error: str | None = None
    model_calls: int = 0
    tool_calls: int = 0


RuntimeEventPayload = (
    TurnStartPayload
    | UserMessagePayload
    | ModelRequestPayload
    | AssistantDeltaPayload
    | AssistantMessagePayload
    | ToolCallPayload
    | ToolResultPayload
    | ErrorPayload
    | TurnEndPayload
)


EVENT_PAYLOAD_MODELS: dict[str, type[RuntimeEventPayload]] = {
    EVENT_TURN_START: TurnStartPayload,
    EVENT_USER_MESSAGE: UserMessagePayload,
    EVENT_MODEL_REQUEST: ModelRequestPayload,
    EVENT_ASSISTANT_DELTA: AssistantDeltaPayload,
    EVENT_ASSISTANT_MESSAGE: AssistantMessagePayload,
    EVENT_TOOL_CALL: ToolCallPayload,
    EVENT_TOOL_RESULT: ToolResultPayload,
    EVENT_ERROR: ErrorPayload,
    EVENT_TURN_END: TurnEndPayload,
}


class EventPayloadBuilder:
    @staticmethod
    def build_turn_start_payload() -> dict[str, Any]:
        return {}

    @staticmethod
    def build_user_message_payload(content: str) -> dict[str, Any]:
        return payload_to_dict(UserMessagePayload(content=content))

    @staticmethod
    def build_model_request_payload(
        model: str,
        stream: bool,
        request_index: int,
        messages: list[dict],
        tools: list[dict],
    ) -> dict[str, Any]:
        return payload_to_dict(
            ModelRequestPayload(
                model=model,
                stream=stream,
                request_index=request_index,
                message_count=len(messages),
                tool_count=len(tools),
                tool_names=_tool_names(tools),
                total_message_chars=_total_message_chars(messages),
            )
        )

    @staticmethod
    def build_assistant_delta_payload(delta: str) -> dict[str, Any]:
        return payload_to_dict(AssistantDeltaPayload(delta=delta))

    @staticmethod
    def build_assistant_message_payload(
        content: str,
        tool_call_count: int,
        final: bool,
        streamed: bool,
        usage: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return payload_to_dict(
            AssistantMessagePayload(
                content=content,
                tool_call_count=tool_call_count,
                final=final,
                streamed=streamed,
                usage=usage,
            )
        )

    @staticmethod
    def build_tool_call_payload(
        tool_call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        return payload_to_dict(
            ToolCallPayload(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                arguments=arguments,
            )
        )

    @staticmethod
    def build_tool_result_payload(
        tool_call_id: str,
        tool_name: str,
        ok: bool,
        output: Any = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        return payload_to_dict(
            ToolResultPayload(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                ok=ok,
                output=output,
                error=error,
            )
        )

    @staticmethod
    def build_error_payload(message: str) -> dict[str, Any]:
        return payload_to_dict(ErrorPayload(message=message))

    @staticmethod
    def build_turn_end_payload(
        status: str,
        exit_reason: str,
        error: str | None = None,
        model_calls: int = 0,
        tool_calls: int = 0,
    ) -> dict[str, Any]:
        return payload_to_dict(
            TurnEndPayload(
                status=status,
                exit_reason=exit_reason,
                error=error,
                model_calls=model_calls,
                tool_calls=tool_calls,
            )
        )


def payload_to_dict(payload: RuntimeEventPayload) -> dict[str, Any]:
    return asdict(payload)


def _tool_names(tool_schemas: list[dict]) -> list[str]:
    names: list[str] = []
    for schema in tool_schemas:
        function = schema.get("function")
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        if isinstance(name, str) and name:
            names.append(name)
    return names


def _total_message_chars(messages: list[dict]) -> int:
    return sum(_content_chars(message.get("content")) for message in messages)


def _content_chars(content: Any) -> int:
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(_content_chars(item) for item in content)
    if isinstance(content, dict):
        return sum(_content_chars(item) for item in content.values())
    return 0
