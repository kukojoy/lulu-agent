from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from lulu_agent.llm.usage import extract_usage


@dataclass(frozen=True)
class ModelConfig:
    model: str
    base_url_host: str
    timeout_seconds: float


@dataclass(frozen=True)
class ModelRequest:
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None
    stream: bool = True


@dataclass(frozen=True)
class AssistantToolFunction:
    name: str
    arguments: str


@dataclass(frozen=True)
class AssistantToolCall:
    id: str | None
    type: str
    function: AssistantToolFunction


@dataclass(frozen=True)
class AssistantMessage:
    content: str | None
    tool_calls: list[AssistantToolCall]


@dataclass(frozen=True)
class ModelResponse:
    message: AssistantMessage
    streamed: bool
    usage: dict[str, Any] | None = None


class StreamingAssistantResponseBuilder:
    def __init__(self):
        self.content_parts: list[str] = []
        self.tool_call_parts: dict[int, dict] = {} # index -> tool_call
        self.streamed = False
        self.usage: dict[str, Any] | None = None

    def consume(self, chunks: Iterable) -> Iterable[str]:
        for chunk in chunks:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                self.usage = extract_usage(chunk)
                continue

            delta = choices[0].delta
            content_delta = getattr(delta, "content", None)
            if content_delta:
                self.streamed = True
                self.content_parts.append(content_delta)
                yield content_delta

            for tool_call_delta in getattr(delta, "tool_calls", None) or []:
                self.streamed = True
                self._merge_tool_call_delta(tool_call_delta)

    def build(self) -> ModelResponse:
        return ModelResponse(
            message=AssistantMessage(
                content="".join(self.content_parts) or None,
                tool_calls=self._build_tool_calls(),
            ),
            streamed=self.streamed,
            usage=self.usage,
        )

    def _merge_tool_call_delta(self, tool_call_delta) -> None:
        index = getattr(tool_call_delta, "index", None)
        if index is None:
            index = len(self.tool_call_parts)

        part = self.tool_call_parts.setdefault(
            index,
            {
                "id": None,
                "type": "function",
                "function_name": "",
                "arguments": "",
            },
        )
        if getattr(tool_call_delta, "id", None):
            part["id"] = tool_call_delta.id
        if getattr(tool_call_delta, "type", None):
            part["type"] = tool_call_delta.type

        function_delta = getattr(tool_call_delta, "function", None)
        if not function_delta:
            return
        if getattr(function_delta, "name", None):
            part["function_name"] += function_delta.name
        if getattr(function_delta, "arguments", None):
            part["arguments"] += function_delta.arguments

    def _build_tool_calls(self) -> list[AssistantToolCall]:
        tool_calls = []
        for index in sorted(self.tool_call_parts):
            part = self.tool_call_parts[index]
            tool_calls.append(
                AssistantToolCall(
                    id=part["id"],
                    type=part["type"],
                    function=AssistantToolFunction(
                        name=part["function_name"],
                        arguments=part["arguments"],
                    ),
                )
            )
        return tool_calls
