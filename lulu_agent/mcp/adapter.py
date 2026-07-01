"""MCP 工具适配器

负责把 MCP 工具信息转换成 lulu-agent Tool
"""

import re
from dataclasses import dataclass
from typing import Any, Callable

from lulu_agent.mcp.client import MCPClient
from lulu_agent.tools import Tool, ToolResult


MCP_TOOL_NAME_PREFIX = "mcp"
MCP_TOOL_NAME_PATTERN = re.compile(r"[^A-Za-z0-9_]")


@dataclass(frozen=True)
class MCPToolAdapterError:
    """MCP 工具适配器错误"""
    name: str
    error: str


@dataclass(frozen=True)
class MCPToolAdapterResult:
    """MCP 工具适配器结果"""
    tools: list[Tool]
    errors: list[MCPToolAdapterError]


def _build_mcp_tool_name(server_name: str, tool_name: str) -> str:
    parts = [
        MCP_TOOL_NAME_PREFIX,
        _sanitize_name_part(server_name),
        _sanitize_name_part(tool_name),
    ]
    return "_".join(part for part in parts if part)


def _normalize_mcp_input_schema(schema: Any) -> dict[str, Any]:
    """规范化 MCP 工具的输入 schema"""
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return _empty_object_schema()

    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return _empty_object_schema()

    normalized = dict(schema)
    normalized["type"] = "object"
    normalized["properties"] = properties

    required = normalized.get("required", [])
    if isinstance(required, list):
        normalized["required"] = [
            item for item in required if isinstance(item, str) and item in properties
        ]
    elif "required" in normalized:
        normalized["required"] = []

    return normalized


def _sanitize_name_part(value: str) -> str:
    sanitized = MCP_TOOL_NAME_PATTERN.sub("_", value.strip())
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    return sanitized


def _empty_object_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {},
    }


def _build_tool_description(server_name: str, info: dict[str, Any]) -> str:
    """构建工具描述信息: [MCP:server_name] description"""
    description = info.get("description", "")
    if not isinstance(description, str) or not description.strip():
        description = "External MCP tool."
    return f"[MCP:{server_name}] {description.strip()}"


def _make_handler(client: MCPClient, raw_tool_name: str) -> Callable[[dict[str, Any]], ToolResult]:
    """构建工具处理函数, 调用 MCP 工具并返回结果"""
    def handler(args: dict[str, Any]) -> ToolResult:
        result = client.call_tool(raw_tool_name, args)
        if not result.ok:
            return ToolResult(ok=False, error=result.error)
        if _is_mcp_error_result(result.output):
            return ToolResult(
                ok=False,
                output=result.output,
                error=_extract_mcp_error_text(result.output),
            )
        return ToolResult(ok=True, output=result.output)

    return handler


def _is_mcp_error_result(output: Any) -> bool:
    return isinstance(output, dict) and output.get("isError") is True


def _extract_mcp_error_text(output: dict[str, Any]) -> str:
    content = output.get("content")
    if isinstance(content, list):
        texts = [
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        ]
        text = "\n".join(item for item in texts if item.strip()).strip()
        if text:
            return text
    return "MCP tool returned an error result."


# === 唯一对外接口 ===
def build_mcp_tools(
    server_name: str,
    tool_infos: list[dict[str, Any]],
    client: MCPClient,
    existing_names: set[str] | None = None,
) -> MCPToolAdapterResult:
    """将 MCP 工具转换为 lulu-agent Tool
    
    Args:
        server_name (str): MCP 服务器名称
        tool_infos (list[dict[str, Any]]): MCP 工具信息列表
        client (MCPClient): MCP 客户端实例
        existing_names (set[str] | None): 已存在的工具名称集合, 用于避免名称冲突
    """
    existing = existing_names or set()
    tools: list[Tool] = []
    errors: list[MCPToolAdapterError] = []

    for info in tool_infos:
        raw_name = info.get("name", "")
        if not isinstance(raw_name, str) or not raw_name.strip():
            errors.append(
                MCPToolAdapterError(
                    name="",
                    error="MCP tool name must be a non-empty string.",
                )
            )
            continue

        name = _build_mcp_tool_name(server_name, raw_name)
        if name in existing:
            errors.append(
                MCPToolAdapterError(
                    name=name,
                    error=f"MCP tool name conflicts with existing tool: {name}",
                )
            )
            continue

        tool = Tool(
            name=name,
            description=_build_tool_description(server_name, info),
            parameters=_normalize_mcp_input_schema(info.get("input_schema")),
            handler=_make_handler(client, raw_name),
        )
        tools.append(tool)
        existing.add(name)

    return MCPToolAdapterResult(tools=tools, errors=errors)
