from __future__ import annotations

from lulu_agent.runtime.events import RuntimeEvent
from lulu_agent.runtime.events import (
    EVENT_USER_MESSAGE,
    EVENT_ASSISTANT_DELTA,
    EVENT_TOOL_CALL,
    EVENT_TOOL_RESULT,
    EVENT_ASSISTANT_MESSAGE,
    EVENT_ERROR
)
from uuid import uuid4


class EventSink:
    def emit(self, event: RuntimeEvent) -> None:
        pass


class NoopEventSink(EventSink):
    def emit(self, event: RuntimeEvent) -> None:
        return None


class RecordingEventSink(EventSink):
    def __init__(self):
        self.events: list[RuntimeEvent] = []

    def emit(self, event: RuntimeEvent) -> None:
        self.events.append(event)


class CompositeEventSink(EventSink):
    def __init__(self, sinks: list[EventSink] | None = None):
        if not sinks:
            self.sinks = [NoopEventSink()]
        else:
            self.sinks = sinks

    def emit(self, event: RuntimeEvent) -> None:
        for sink in self.sinks:
            try:
                sink.emit(event)
            except Exception:
                continue


class PersistentEventSink(EventSink):
    def __init__(self, store, session_id: str):
        self.store = store
        self.session_id = session_id

    def emit(self, event: RuntimeEvent) -> None:
        self.store.append_event(self.session_id, event)


class CliEventSink(EventSink):
    COLOR_CYAN = "\033[36m"
    COLOR_GREEN = "\033[32m"
    COLOR_YELLOW = "\033[33m"
    COLOR_MAGENTA = "\033[35m"
    COLOR_RED = "\033[31m"
    COLOR_RESET = "\033[0m"

    def __init__(self):
        self._is_streaming = False

    def emit(self, event: RuntimeEvent) -> None:
        if event.type == EVENT_USER_MESSAGE:
            print(
                self._color(
                    self.COLOR_CYAN,
                    f"[user query:] {event.payload.get('content', '')}",
                )
            )
        elif event.type == EVENT_ASSISTANT_DELTA:
            if not self._is_streaming:
                print(
                    self._color(self.COLOR_GREEN, "[agent response:]"),
                    end=" ",
                    flush=True,
                )
                self._is_streaming = True
            print(
                self._color(self.COLOR_GREEN, event.payload.get("delta", "")),
                end="",
                flush=True,
            )
        elif event.type == EVENT_TOOL_CALL:
            print(
                self._color(
                    self.COLOR_YELLOW,
                    f"[tool] {event.payload.get('tool_name')} "
                    f"args={event.payload.get('arguments', {})}",
                )
            )
        elif event.type == EVENT_TOOL_RESULT:
            print(
                self._color(
                    self.COLOR_MAGENTA,
                    f"[tool result] ok={event.payload.get('ok')} "
                    f"output={event.payload.get('output')} "
                    f"error={event.payload.get('error')}",
                )
            )
        elif event.type == EVENT_ASSISTANT_MESSAGE:
            if event.payload.get("streamed"):
                self._finish_streaming()
            elif event.payload.get("content"):
                print(
                    self._color(
                        self.COLOR_GREEN,
                        f"[agent response:] {event.payload.get('content', '')}",
                    )
                )
        elif event.type == EVENT_ERROR:
            self._finish_streaming()
            print(
                self._color(
                    self.COLOR_RED,
                    f"[error] {event.payload.get('message', '')}",
                )
            )

    def _color(self, color: str, text: str) -> str:
        return f"{color}{text}{self.COLOR_RESET}"

    def _finish_streaming(self) -> None:
        if self._is_streaming:
            print()
            self._is_streaming = False


def new_turn_id() -> str:
    return f"turn-{uuid4().hex[:8]}"
