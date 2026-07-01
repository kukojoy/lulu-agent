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


class NoopEventSink:
    def emit(self, event: RuntimeEvent) -> None:
        return None


class RecordingEventSink:
    def __init__(self):
        self.events: list[RuntimeEvent] = []

    def emit(self, event: RuntimeEvent) -> None:
        self.events.append(event)


class CliEventSink:
    COLOR_CYAN = "\033[36m"
    COLOR_GREEN = "\033[32m"
    COLOR_YELLOW = "\033[33m"
    COLOR_MAGENTA = "\033[35m"
    COLOR_RED = "\033[31m"
    COLOR_RESET = "\033[0m"

    def __init__(self):
        self._streaming_turns: set[str] = set()

    def emit(self, event: RuntimeEvent) -> None:
        if event.type == EVENT_USER_MESSAGE:
            print(
                self._color(
                    self.COLOR_CYAN,
                    f"[user query:] {event.payload.get('content', '')}",
                )
            )
        elif event.type == EVENT_ASSISTANT_DELTA:
            if event.turn_id not in self._streaming_turns:
                print(
                    self._color(self.COLOR_GREEN, "[agent response:]"),
                    end=" ",
                    flush=True,
                )
                self._streaming_turns.add(event.turn_id)
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
        elif event.type == EVENT_ASSISTANT_MESSAGE and event.payload.get("final"):
            if event.payload.get("streamed"):
                print()
            else:
                print(
                    self._color(
                        self.COLOR_GREEN,
                        f"[agent response:] {event.payload.get('content', '')}",
                    )
                )
        elif event.type == EVENT_ERROR:
            print(
                self._color(
                    self.COLOR_RED,
                    f"[error] {event.payload.get('message', '')}",
                )
            )

    def _color(self, color: str, text: str) -> str:
        return f"{color}{text}{self.COLOR_RESET}"


def new_turn_id() -> str:
    return f"turn-{uuid4().hex[:8]}"
