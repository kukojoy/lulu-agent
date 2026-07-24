from typing import Any

from lulu_agent.runtime.events import (
    EVENT_ASSISTANT_DELTA,
    EVENT_ASSISTANT_MESSAGE,
    EVENT_ERROR,
    EVENT_MODEL_REQUEST,
    EVENT_TOOL_CALL,
    EVENT_TOOL_RESULT,
    EVENT_TURN_END,
    EVENT_TURN_START,
    EVENT_USER_MESSAGE,
)
from lulu_agent.storage.trace_store import TraceStore


class TraceInteractionService:
    def __init__(self, trace_store: TraceStore | None = None):
        self.trace_store = trace_store or TraceStore()

    def list_events(
        self,
        session_id: str,
        turn_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.trace_store.load_events(session_id, turn_id=turn_id)

    def build_timeline(
        self,
        session_id: str,
        turn_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return [_timeline_item(record) for record in self.list_events(session_id, turn_id=turn_id)]


def _timeline_item(record: dict[str, Any]) -> dict[str, Any]:
    event_type = record.get("event_type")
    payload = record.get("payload") or {}
    item = {
        "event_type": event_type,
        "turn_id": record.get("turn_id"),
        "timestamp": record.get("timestamp"),
        "label": _event_label(event_type),
        "detail": _event_detail(event_type, payload),
        "payload": payload,
    }
    if event_type in {EVENT_TOOL_CALL, EVENT_TOOL_RESULT}:
        item["tool_name"] = payload.get("tool_name")
        item["tool_call_id"] = payload.get("tool_call_id")
    if event_type == EVENT_TOOL_RESULT:
        item["ok"] = payload.get("ok")
        item["error"] = payload.get("error")
        item["error_type"] = payload.get("error_type")
    return item


def _event_label(event_type: str | None) -> str:
    labels = {
        EVENT_TURN_START: "Turn started",
        EVENT_USER_MESSAGE: "User message",
        EVENT_MODEL_REQUEST: "Model request",
        EVENT_ASSISTANT_DELTA: "Assistant delta",
        EVENT_ASSISTANT_MESSAGE: "Assistant message",
        EVENT_TOOL_CALL: "Tool call",
        EVENT_TOOL_RESULT: "Tool result",
        EVENT_ERROR: "Error",
        EVENT_TURN_END: "Turn ended",
    }
    return labels.get(event_type, str(event_type or "unknown"))


def _event_detail(event_type: str | None, payload: dict[str, Any]) -> str:
    if event_type == EVENT_USER_MESSAGE:
        return str(payload.get("content") or "")
    if event_type == EVENT_MODEL_REQUEST:
        return (
            f"model={payload.get('model', '')} "
            f"messages={payload.get('message_count', 0)} "
            f"tools={payload.get('tool_count', 0)}"
        )
    if event_type == EVENT_ASSISTANT_DELTA:
        return str(payload.get("delta") or "")
    if event_type == EVENT_ASSISTANT_MESSAGE:
        return str(payload.get("content") or "")
    if event_type == EVENT_TOOL_CALL:
        return f"{payload.get('tool_name')} args={payload.get('arguments', {})}"
    if event_type == EVENT_TOOL_RESULT:
        return f"{payload.get('tool_name')} ok={payload.get('ok')}"
    if event_type == EVENT_ERROR:
        return str(payload.get("message") or "")
    if event_type == EVENT_TURN_END:
        return f"{payload.get('status')} / {payload.get('exit_reason')}"
    return ""
