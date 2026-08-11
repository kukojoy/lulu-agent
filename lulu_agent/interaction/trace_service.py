from typing import Any

from lulu_agent.runtime.events import (
    EVENT_ASSISTANT_DELTA,
    EVENT_ASSISTANT_MESSAGE,
    EVENT_MODEL_REQUEST,
    EVENT_MODEL_RETRY,
    EVENT_REVIEW_SUMMARY,
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

    def build_turns(self, session_id: str) -> list[dict[str, Any]]:
        turns_by_id: dict[str, dict[str, Any]] = {}
        for item in self.build_timeline(session_id):
            turn_id = item.get("turn_id")
            if not isinstance(turn_id, str) or not turn_id:
                continue
            turn = turns_by_id.setdefault(turn_id, _empty_turn(turn_id))
            turn["event_count"] += 1
            _update_turn_summary(turn, item)
            if item.get("event_type") != EVENT_ASSISTANT_DELTA:
                turn["items"].append(item)
        for turn in turns_by_id.values():
            turn["items"].sort(key=lambda item: item.get("event_type") == EVENT_REVIEW_SUMMARY)
        return list(turns_by_id.values())


def _timeline_item(record: dict[str, Any]) -> dict[str, Any]:
    event_type = record.get("event_type")
    payload = record.get("payload") or {}
    item = {
        "event_type": event_type,
        "turn_id": record.get("turn_id"),
        "timestamp": record.get("timestamp"),
        "label": _event_label(event_type),
        "payload": payload,
    }
    return item


def _event_label(event_type: str | None) -> str:
    labels = {
        EVENT_TURN_START: "Turn started",
        EVENT_USER_MESSAGE: "User message",
        EVENT_MODEL_REQUEST: "Model request",
        EVENT_MODEL_RETRY: "Model retry",
        EVENT_ASSISTANT_DELTA: "Assistant delta",
        EVENT_ASSISTANT_MESSAGE: "Assistant message",
        EVENT_TOOL_CALL: "Tool call",
        EVENT_TOOL_RESULT: "Tool result",
        EVENT_REVIEW_SUMMARY: "Review summary",
        EVENT_TURN_END: "Turn ended",
    }
    return labels.get(event_type, str(event_type or "unknown"))


def _empty_turn(turn_id: str) -> dict[str, Any]:
    return {
        "turn_id": turn_id,
        "started_at": None,
        "ended_at": None,
        "status": "running",
        "exit_reason": None,
        "error": None,
        "error_type": None,
        "event_count": 0,
        "model_request_count": 0,
        "model_retry_count": 0,
        "assistant_delta_count": 0,
        "tool_call_count": 0,
        "tool_result_count": 0,
        "items": [],
    }


def _update_turn_summary(turn: dict[str, Any], item: dict[str, Any]) -> None:
    event_type = item.get("event_type")
    timestamp = item.get("timestamp")
    if turn["started_at"] is None:
        turn["started_at"] = timestamp
    if event_type == EVENT_MODEL_REQUEST:
        turn["model_request_count"] += 1
    elif event_type == EVENT_MODEL_RETRY:
        turn["model_retry_count"] += 1
    elif event_type == EVENT_ASSISTANT_DELTA:
        turn["assistant_delta_count"] += 1
    elif event_type == EVENT_TOOL_CALL:
        turn["tool_call_count"] += 1
    elif event_type == EVENT_TOOL_RESULT:
        turn["tool_result_count"] += 1
    elif event_type == EVENT_TURN_END:
        payload = item.get("payload") or {}
        turn["ended_at"] = timestamp
        turn["status"] = payload.get("status")
        turn["exit_reason"] = payload.get("exit_reason")
        turn["error"] = payload.get("error")
        turn["error_type"] = payload.get("error_type")
