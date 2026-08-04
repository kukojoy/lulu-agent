"""MCP 工具注册器

向工具层提供接口: register_mcp_tools, 内部流程:
1. [mcp/config.py]   load_mcp_config(config_path) -> MCPConfigLoadResult -> servers (List[MCPServerConfig])
2. [mcp/client.py]   for server in servers: MCPClient.list_tools() -> MCPClientResult -> tool_infos
3. [mcp/adapter.py]  build_mcp_tools(tool_infos) -> MCPToolAdapterResult -> tools
4. [mcp/registry.py] for tool in tools: tools.register(tool)
"""
from dataclasses import dataclass
from pathlib import Path

from lulu_agent.mcp.config import DEFAULT_MCP_CONFIG_PATH, load_mcp_config
from lulu_agent.mcp.client import MCPClient
from lulu_agent.mcp.adapter import MCPToolAdapterIssue, build_mcp_tools

from lulu_agent.tools import ToolRegistry


@dataclass(frozen=True)
class MCPRegistryIssue:
    """MCP 注册问题信息"""
    server: str
    issue_message: str


@dataclass(frozen=True)
class MCPRegistryResult:
    """MCP 注册结果"""
    registered: list[str]
    issues: list[MCPRegistryIssue]


def _extract_tool_infos(output) -> list[dict]:
    if isinstance(output, dict):
        tools = output.get("tools", [])
        return tools if isinstance(tools, list) else []
    return []


def _adapter_issue_to_registry_issue(
    server_name: str,
    issue: MCPToolAdapterIssue,
) -> MCPRegistryIssue:
    name = f"{issue.name}: " if issue.name else ""
    return MCPRegistryIssue(server=server_name, issue_message=f"{name}{issue.issue_message}")


# === 唯一对外接口 ===
def register_mcp_tools(
    registry: ToolRegistry,
    config_path: str | Path = DEFAULT_MCP_CONFIG_PATH,
) -> MCPRegistryResult:
    """注册 MCP 工具到工具注册表
    
    Returns:
        MCPRegistryResult: 注册结果，包括注册成功的工具名称列表和问题信息列表
    """
    config_result = load_mcp_config(config_path)
    registered: list[str] = []
    issues = [ # 将 MCPConfigIssue 转换为 MCPRegistryIssue
        MCPRegistryIssue(server="", issue_message=f"{issue.path}: {issue.issue_message}")
        for issue in config_result.issues
    ]

    for server_config in config_result.servers:
        client = MCPClient(server_config)
        discovery = client.list_tools()
        if not discovery.ok:
            issues.append(
                MCPRegistryIssue(
                    server=server_config.name,
                    issue_message=discovery.error or "MCP tool discovery failed.",
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

        for issue in adapter_result.issues:
            issues.append(_adapter_issue_to_registry_issue(server_config.name, issue))

        for tool in adapter_result.tools:
            try:
                registry.register(
                    tool,
                    safety_profile=server_config.safety_profile,
                )
            except ValueError as exc:
                issues.append(MCPRegistryIssue(server=server_config.name, issue_message=str(exc)))
                continue
            registered.append(tool.name)

    return MCPRegistryResult(registered=registered, issues=issues)
