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
    message_count: int
    tool_count: int


@dataclass(frozen=True)
class AssistantDeltaPayload:
    delta: str


@dataclass(frozen=True)
class AssistantMessagePayload:
    content: str
    tool_call_count: int
    final: bool
    streamed: bool


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


def payload_to_dict(payload: RuntimeEventPayload) -> dict[str, Any]:
    return asdict(payload)
