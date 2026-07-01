"""AI 流式响应消息处理器

对外提供 StreamingAssistantResponseBuilder 类，用于处理流式响应消息，并构建最终的 AssistantResponse 对象
主要接口: 
- consume(): 消费流式响应消息块
- build(): 构建最终的 AssistantResponse 对象, 包含 message (content, tool_calls) 和 streamed 标志
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


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
class AssistantResponse:
    message: AssistantMessage
    streamed: bool


class StreamingAssistantResponseBuilder:
    def __init__(self):
        self.content_parts: list[str] = []
        self.tool_call_parts: dict[int, dict] = {} # index -> tool_call
        self.streamed = False

    def consume(self, chunks: Iterable) -> Iterable[str]:
        """消费流式响应消息块
        
        运行逻辑:
        1. yield content_delta, 供即时 emit
        2. self.content_parts.append(content_delta), 用于拼接成完整 content 内容
        3. self._merge_tool_call_delta(tool_call_delta) -> self.tool_call_parts[index] = {id, type, function_name, arguments}
        """
        for chunk in chunks:
            delta = chunk.choices[0].delta
            content_delta = getattr(delta, "content", None)
            if content_delta:
                self.streamed = True
                self.content_parts.append(content_delta)
                yield content_delta

            for tool_call_delta in getattr(delta, "tool_calls", None) or []:
                self.streamed = True
                self._merge_tool_call_delta(tool_call_delta)

    def build(self) -> AssistantResponse:
        """流式模式中构建完整响应对象"""
        return AssistantResponse(
            message=AssistantMessage(
                content="".join(self.content_parts) or None,
                tool_calls=self._build_tool_calls(),
            ),
            streamed=self.streamed,
        )

    def _merge_tool_call_delta(self, tool_call_delta) -> None:
        """将 tool_call_delta 拼接到 self.tool_call_parts 中
        
        tool_call_delta.index 用于标识到特定的 tool_call, 并表示了工具的调用顺序
        tool_call_parts[index] = {id, type, function_name, arguments} (字段追加)
        """
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
        """按工具调用顺序, 将 self.tool_call_parts 转换为 list[AssistantToolCall]"""
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
