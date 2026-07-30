import json
from dataclasses import dataclass
from typing import Any

from lulu_agent.runtime.errors import (
    ERROR_EXECUTION,
    ERROR_INVALID_ARGUMENTS,
    ERROR_OUTPUT_TRUNCATED,
    ERROR_TIMEOUT,
    ERROR_UNKNOWN_TOOL,
    ErrorType,
    LuluError,
)
from lulu_agent.tools.registry import ToolRegistry
from lulu_agent.tools.tool import Tool, ToolResult
from lulu_agent.tools.utils import truncate_middle_text


class ToolRuntimeError(LuluError):
    def __init__(self, error_message: str, error_type: ErrorType = ERROR_INVALID_ARGUMENTS):
        super().__init__(error_message, error_type)


MAX_TOOL_RESULT_JSON_CHARS = 120_000
TOOL_RESULT_PREVIEW_CHARS = 4_000

JSON_TYPE_CHECKS = {
    "array": list,
    "boolean": bool,
    "object": dict,
    "string": str,
}

@dataclass(frozen=True)
class ToolCall:
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]
    parse_error: ToolResult | None = None


class ToolRuntime:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def decode(self, raw_tool_call) -> ToolCall:
        tool_call_id = getattr(raw_tool_call, "id", "")
        function = getattr(raw_tool_call, "function", None)
        tool_name = getattr(function, "name", "")
        raw_arguments = getattr(function, "arguments", None)

        if not raw_arguments:
            return ToolCall(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                arguments={},
            )

        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            return ToolCall(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                arguments={},
                parse_error=ToolResult(
                    ok=False,
                    error=f"Invalid tool arguments JSON: {exc.msg}",
                    error_type=ERROR_INVALID_ARGUMENTS,
                ),
            )

        if not isinstance(arguments, dict):
            return ToolCall(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                arguments={},
                parse_error=ToolResult(
                    ok=False,
                    error="Tool arguments must be a JSON object.",
                    error_type=ERROR_INVALID_ARGUMENTS,
                ),
            )

        return ToolCall(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments=arguments,
        )

    def run(self, tool_call: ToolCall) -> ToolResult:
        if tool_call.parse_error is not None:
            return tool_call.parse_error

        tool = self.registry.get(tool_call.tool_name)
        if not tool:
            return ToolResult(
                ok=False,
                error=f"Unknown tool: {tool_call.tool_name}",
                error_type=ERROR_UNKNOWN_TOOL,
            )

        try:
            _validate_tool_args(tool, tool_call.arguments)
        except ToolRuntimeError as exc:
            return ToolResult(
                ok=False,
                error=exc.error_message,
                error_type=exc.error_type,
            )

        try:
            result = tool.handler(tool_call.arguments)
        except TimeoutError as exc:
            result = ToolResult(
                ok=False,
                error=str(exc) or f"Tool timed out: {tool_call.tool_name}",
                error_type=ERROR_TIMEOUT,
            )
        except Exception as exc:
            result = ToolResult(
                ok=False,
                error=str(exc),
                error_type=ERROR_EXECUTION,
            )

        if not isinstance(result, ToolResult):
            return ToolResult(
                ok=False,
                error="Tool handler must return ToolResult.",
                error_type=ERROR_EXECUTION,
            )

        if not result.ok and result.error_type is None:
            result.error_type = ERROR_EXECUTION

        return self._truncate_result(result)

    def _truncate_result(self, result: ToolResult) -> ToolResult:
        """工具结果截断
        
        处理逻辑:
            1. 将 ToolResult 转换为 JSON 字符串
            2. if 长度 <= MAX_TOOL_RESULT_JSON_CHARS, 直接返回原始结果
            3. 截断 JSON 字符串, 并返回一个新的 ToolResult, 调整字段包括:
                - output: 注入截断预览和相关信息
                - error_type: 原错误类型或 ERROR_OUTPUT_TRUNCATED
                - metadata: 元数据, 注入截断信息
                - truncated: True
        """
        result_json = result.to_json()
        if len(result_json) <= MAX_TOOL_RESULT_JSON_CHARS:
            return result

        metadata = dict(result.metadata or {})
        metadata.update(
            {
                "truncated_by": "tool_runtime_json_chars",
                "original_json_length": len(result_json),
                "max_json_chars": MAX_TOOL_RESULT_JSON_CHARS,
            }
        )
        preview = truncate_middle_text(result_json, TOOL_RESULT_PREVIEW_CHARS)
        return ToolResult(
            ok=result.ok,
            output={
                "preview": preview,
                "tips": "Tool result was truncated by ToolRuntime.",
            },
            error=result.error,
            error_type=result.error_type or ERROR_OUTPUT_TRUNCATED,
            metadata=metadata,
            truncated=True,
        )


def _validate_tool_args(tool: Tool, args: dict[str, Any]) -> None:
    parameters = tool.parameters
    required = parameters.get("required", [])
    properties = parameters.get("properties", {})

    for name in required:
        if name not in args:
            raise ToolRuntimeError(
                f"Missing required argument '{name}' for tool '{tool.name}'.",
            )

    for name, value in args.items():
        schema = properties.get(name)
        if not schema:
            continue

        expected_type = schema.get("type")
        if not expected_type:
            continue

        if not _matches_json_type(value, expected_type):
            raise ToolRuntimeError(
                f"Invalid argument '{name}' for tool '{tool.name}': "
                f"expected {expected_type}, got {_json_type_name(value)}."
            )


def _matches_json_type(value: Any, expected_type: str) -> bool:
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)

    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    check = JSON_TYPE_CHECKS.get(expected_type)
    if not check:
        return True

    return isinstance(value, check)


def _json_type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if value is None:
        return "null"
    return type(value).__name__
