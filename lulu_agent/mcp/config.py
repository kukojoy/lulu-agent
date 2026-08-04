import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lulu_agent.safety import SAFETY_PROFILE_APPROVAL_REQUIRED, SAFETY_PROFILE_TRUSTED


DEFAULT_MCP_CONFIG_PATH = Path.home() / ".lulu" / "mcp.json"
DEFAULT_MCP_SERVER_TIMEOUT = 30.0
DEFAULT_MCP_SERVER_SAFETY_PROFILE = SAFETY_PROFILE_TRUSTED
MCP_SERVER_SAFETY_PROFILES = frozenset(
    {
        SAFETY_PROFILE_APPROVAL_REQUIRED,
        SAFETY_PROFILE_TRUSTED,
    }
)
MCP_SERVER_NAME_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$")


@dataclass(frozen=True)
class MCPServerConfig:
    """单个 MCP 服务器配置
    
    Attributes:
        name (str): MCP 服务器名称, 用于标识不同的 MCP 服务器
        command (str): 请求 MCP 服务器的命令
        args (list[str]): 请求 MCP 服务器的命令行参数列表
        env (dict[str, str]): 请求 MCP 服务器的环境变量字典
        timeout (float): 请求 MCP 服务器的超时时间, 单位为秒
        safety_profile (str): MCP 工具调用安全档位
    """
    name: str
    command: str
    args: list[str]
    env: dict[str, str]
    timeout: float
    safety_profile: str = DEFAULT_MCP_SERVER_SAFETY_PROFILE


@dataclass(frozen=True)
class MCPConfigIssue:
    """单个 MCP 配置项加载问题

    Attributes:
        path (str): MCP 配置文件路径
        issue_message (str): 问题信息
    """
    path: str
    issue_message: str


@dataclass(frozen=True)
class MCPConfigResult:
    """MCP 配置加载结果

    Attributes:
        path (str): MCP 配置文件路径
        servers (list[MCPServerConfig]): MCP 服务器配置列表
        issues (list[MCPConfigIssue]): 加载问题列表
    """
    path: str
    servers: list[MCPServerConfig]
    issues: list[MCPConfigIssue]


def _parse_server_config(name: str, raw_server: Any) -> MCPServerConfig | None:
    """解析单个 MCP 服务器配置
    
    Args:
        name (str): MCP 服务器名称
        raw_server (Any): MCP 服务器配置原始数据
    
    Returns:
        MCPServerConfig | None: MCP 服务器配置对象, 如果配置被禁用则返回 None
    """
    if not isinstance(name, str) or not _is_valid_server_name(name): # 检查 name
        raise ValueError(
            "MCP server name must use only ASCII letters, numbers, or hyphens."
        )

    # 检查 raw_server 及其中的各个字段
    if not isinstance(raw_server, dict): # 检查 raw_server 是否为 JSON object
        raise ValueError("MCP server config must be a JSON object.")

    enabled = raw_server.get("enabled", True) # 检查 enabled (默认为 True), 设为 False 可禁用服务器配置
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be a boolean.")
    if not enabled:
        return None

    command = raw_server.get("command") # 检查 command
    if not isinstance(command, str) or not command.strip():
        raise ValueError("command must be a non-empty string.")

    args = raw_server.get("args", []) # 检查 args
    if not _is_string_list(args):
        raise ValueError("args must be a list of strings.")

    env = raw_server.get("env", {}) # 检查 env
    if not _is_string_dict(env):
        raise ValueError("env must be an object with string keys and string values.")

    timeout = raw_server.get("timeout", DEFAULT_MCP_SERVER_TIMEOUT) # 检查 timeout (默认为 DEFAULT_MCP_SERVER_TIMEOUT)
    if not _is_positive_number(timeout):
        raise ValueError("timeout must be a positive number.")

    safety_profile = raw_server.get("safety_profile", DEFAULT_MCP_SERVER_SAFETY_PROFILE)
    if safety_profile not in MCP_SERVER_SAFETY_PROFILES:
        raise ValueError("safety_profile must be trusted or approval_required.")

    # 封装为 MCPServerConfig 对象
    return MCPServerConfig(
        name=name,
        command=command.strip(),
        args=list(args),
        env=dict(env),
        timeout=float(timeout),
        safety_profile=str(safety_profile),
    )


def _is_valid_server_name(name: str) -> bool:
    return bool(MCP_SERVER_NAME_PATTERN.fullmatch(name))


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_string_dict(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(key, str) and isinstance(item, str)
        for key, item in value.items()
    )


def _is_positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


# === 唯一对外接口 ===
def load_mcp_config(path: str | Path = DEFAULT_MCP_CONFIG_PATH) -> MCPConfigResult:
    """获取 MCP 配置
    
    Args:
        path (str | Path): MCP 配置文件路径, 默认为 ~/.lulu/mcp.json
    
    Returns:
        MCPConfigResult: MCP 配置加载结果, 包含服务器配置列表和错误信息
    """
    config_path = Path(path)
    resolved_path = str(config_path.resolve())

    if not config_path.exists(): # 配置文件不存在, 返回空配置
        return MCPConfigResult(
            path=resolved_path,
            servers=[],
            issues=[],
        )

    try:
        raw_config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc: # 配置文件不是有效的 JSON
        return MCPConfigResult(
            path=resolved_path,
            servers=[],
            issues=[
                MCPConfigIssue(
                    path=resolved_path,
                    issue_message=f"Invalid MCP config JSON: {exc.msg}",
                )
            ],
        )

    if not isinstance(raw_config, dict): # 配置文件不是 JSON object
        return MCPConfigResult(
            path=resolved_path,
            servers=[],
            issues=[
                MCPConfigIssue(
                    path=resolved_path,
                    issue_message="MCP config must be a JSON object.",
                )
            ],
        )

    raw_servers = raw_config.get("mcpServers", {})
    if raw_servers is None:
        raw_servers = {}
    if not isinstance(raw_servers, dict): # mcpServers 不是 JSON object
        return MCPConfigResult(
            path=resolved_path,
            servers=[],
            issues=[
                MCPConfigIssue(
                    path=resolved_path,
                    issue_message="mcpServers must be a JSON object.",
                )
            ],
        )

    servers: list[MCPServerConfig] = []
    issues: list[MCPConfigIssue] = []
    # 按名称排序解析 MCP 服务器配置
    for name, raw_server in sorted(raw_servers.items(), key=lambda item: item[0]):
        server_path = f"{resolved_path}:mcpServers.{name}"
        try:
            server = _parse_server_config(name, raw_server)
        except ValueError as exc:
            issues.append(MCPConfigIssue(path=server_path, issue_message=str(exc)))
            continue

        if server is not None:
            servers.append(server)

    return MCPConfigResult(
        path=resolved_path,
        servers=servers,
        issues=issues,
    )
