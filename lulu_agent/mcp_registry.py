"""MCP 工具注册器

向工具层提供接口: register_mcp_tools, 内部流程:
1. [mcp_config.py]   load_mcp_config(config_path) -> MCPConfigLoadResult -> servers (List[MCPServerConfig])
2. [mcp_client.py]   for server in servers: MCPClient.list_tools() -> MCPClientResult -> tool_infos
3. [mcp_adapter.py]  build_mcp_tools(tool_infos) -> MCPToolAdapterResult -> tools
4. [mcp_registry.py] for tool in tools: tools.register(tool)
"""
from dataclasses import dataclass

from lulu_agent.mcp_config import DEFAULT_MCP_CONFIG_PATH, load_mcp_config
from lulu_agent.mcp_client import MCPClient
from lulu_agent.mcp_adapter import MCPToolAdapterError, build_mcp_tools

from lulu_agent.tools import ToolRegistry


@dataclass(frozen=True)
class MCPRegistryError:
    """MCP 注册错误信息"""
    server: str
    error: str


@dataclass(frozen=True)
class MCPRegistryResult:
    """MCP 注册结果"""
    registered: list[str]
    errors: list[MCPRegistryError]


def _extract_tool_infos(output) -> list[dict]:
    if isinstance(output, dict):
        tools = output.get("tools", [])
        return tools if isinstance(tools, list) else []
    return []


def _adapter_error_to_registry_error(
    server_name: str,
    error: MCPToolAdapterError,
) -> MCPRegistryError:
    name = f"{error.name}: " if error.name else ""
    return MCPRegistryError(server=server_name, error=f"{name}{error.error}")


# === 唯一对外接口 ===
def register_mcp_tools(
    registry: ToolRegistry,
    config_path: str = DEFAULT_MCP_CONFIG_PATH,
) -> MCPRegistryResult:
    """注册 MCP 工具到工具注册表
    
    Returns:
        MCPRegistryResult: 注册结果，包括注册成功的工具名称列表和错误信息列表
    """
    config_result = load_mcp_config(config_path)
    registered: list[str] = []
    errors = [ # 将 MCPConfigLoadError 转换为 MCPRegistryError
        MCPRegistryError(server="", error=f"{error.path}: {error.error}")
        for error in config_result.errors
    ]

    for server_config in config_result.servers:
        client = MCPClient(server_config)
        discovery = client.list_tools()
        if not discovery.ok:
            errors.append(
                MCPRegistryError(
                    server=server_config.name,
                    error=discovery.error or "MCP tool discovery failed.",
                )
            )
            continue

        tool_infos = _extract_tool_infos(discovery.output)
        adapter_result = build_mcp_tools(
            server_name=server_config.name,
            tool_infos=tool_infos,
            client=client,
            existing_names=set(registry.names()),
        )

        for error in adapter_result.errors:
            errors.append(_adapter_error_to_registry_error(server_config.name, error))

        for tool in adapter_result.tools:
            try:
                registry.register(tool)
            except ValueError as exc:
                errors.append(MCPRegistryError(server=server_config.name, error=str(exc)))
                continue
            registered.append(tool.name)

    return MCPRegistryResult(registered=registered, errors=errors)
