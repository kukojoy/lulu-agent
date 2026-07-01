"""MCP 客户端

MCPClient 主要对外接口:
- list_tools(): 列出 MCP 服务器上的工具列表
- call_tool(tool_name, arguments): 调用 MCP 服务器上的工具

SDK 相关补充解释:
1. ClientSession, StdioServerParameters, stdio_client 是 mcp SDK 中的类和函数, 用于创建 MCP 客户端会话和与 MCP 服务器进行通信
2. MCPServerConfig => StdioServerParameters
3. stdio_client(StdioServerParameters) => read_stream, write_stream
4. ClientSession(read_stream, write_stream) => session 
5. session.list_tools() / session.call_tool()
"""

import asyncio
from dataclasses import dataclass
from typing import Any, Callable

from lulu_agent.mcp.config import MCPServerConfig


try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    
    MCP_SDK_AVAILABLE = True
except ImportError: # mcp SDK 不可用时, 不支持 MCP 应用, 但不影响其他功能
    ClientSession = None
    StdioServerParameters = None
    stdio_client = None
    MCP_SDK_AVAILABLE = False


@dataclass(frozen=True)
class MCPToolInfo:
    """MCP 工具信息
    
    Attributes:
        name (str): 工具名称
        description (str): 工具描述
        input_schema (dict[str, Any]): 工具输入参数的 JSON Schema
    """
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class MCPClientResult:
    """MCP 客户端调用结果

    Attributes:
        ok (bool): 是否成功
        server (str): MCP 服务器名称
        output (Any): 成功时的输出结果
        error (str | None): 失败时的错误信息
    """
    ok: bool
    server: str
    output: Any = None
    error: str | None = None


class MCPClient:
    def __init__(
        self,
        config: MCPServerConfig,
        client_session_cls: Any = ClientSession,
        stdio_client_fn: Callable | None = stdio_client,
        stdio_params_cls: Any = StdioServerParameters,
    ):
        """MCP 客户端, 和某个具体的 MCP 服务器进行交互
        
        Attributes:
            config (MCPServerConfig): MCP 服务器配置
            client_session_cls (Any): MCP SDK 的 ClientSession 类, 用于创建客户端会话
            stdio_client_fn (Callable | None): MCP SDK 的 stdio_client 函数, 用于创建 stdio 客户端
            stdio_params_cls (Any): MCP SDK 的 StdioServerParameters 类, 用于创建 stdio 客户端参数
        """
        self.config = config
        self.client_session_cls = client_session_cls
        self.stdio_client_fn = stdio_client_fn
        self.stdio_params_cls = stdio_params_cls

    def list_tools(self) -> MCPClientResult:
        """列出 MCP 服务器上的工具列表"""
        if not self.is_available():
            return self._error("MCP SDK is not installed.")

        try:
            tools = asyncio.run(
                asyncio.wait_for(
                    self._list_tools_async(),
                    timeout=self.config.timeout,
                )
            )
        except TimeoutError:
            return self._error("MCP list_tools timed out.")
        except Exception as exc:
            return self._error(f"MCP list_tools failed: {_safe_error(exc)}")

        return MCPClientResult(
            ok=True,
            server=self.config.name,
            output={"tools": tools},
        )

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> MCPClientResult:
        """调用 MCP 服务器上的工具
        
        Args:
            tool_name (str): 工具名称
            arguments (dict[str, Any]): 工具输入参数字典
        """
        if not self.is_available():
            return self._error("MCP SDK is not installed.")

        try:
            result = asyncio.run(
                asyncio.wait_for(
                    self._call_tool_async(tool_name, arguments),
                    timeout=self.config.timeout,
                )
            )
        except TimeoutError:
            return self._error(f"MCP tool call timed out: {tool_name}")
        except Exception as exc:
            return self._error(f"MCP tool call failed: {_safe_error(exc)}")

        return MCPClientResult(
            ok=True,
            server=self.config.name,
            output=result,
        )

    def is_available(self) -> bool:
        return bool(
            self.client_session_cls
            and self.stdio_client_fn
            and self.stdio_params_cls
        )

    async def _list_tools_async(self) -> list[dict[str, Any]]:
        async with self._session() as session:
            response = await session.list_tools()
            return [_tool_to_dict(tool) for tool in _extract_tools(response)]

    async def _call_tool_async(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        async with self._session() as session:
            response = await session.call_tool(tool_name, arguments)
            return _to_plain_data(response)

    def _session(self):
        params = self.stdio_params_cls(
            command=self.config.command,
            args=self.config.args,
            env=self.config.env,
        )
        return _MCPSessionContext(
            params=params,
            stdio_client_fn=self.stdio_client_fn,
            client_session_cls=self.client_session_cls,
        )

    def _error(self, message: str) -> MCPClientResult:
        return MCPClientResult(
            ok=False,
            server=self.config.name,
            error=message,
        )


class _MCPSessionContext:
    def __init__(self, params, stdio_client_fn, client_session_cls):
        self.params = params
        self.stdio_client_fn = stdio_client_fn
        self.client_session_cls = client_session_cls
        self.stdio_context = None
        self.session_context = None
        self.session = None

    async def __aenter__(self):
        self.stdio_context = self.stdio_client_fn(self.params)
        read_stream, write_stream = await self.stdio_context.__aenter__()
        self.session_context = self.client_session_cls(read_stream, write_stream)
        self.session = await self.session_context.__aenter__()
        await self.session.initialize()
        return self.session

    async def __aexit__(self, exc_type, exc, traceback):
        if self.session_context is not None:
            await self.session_context.__aexit__(exc_type, exc, traceback)
        if self.stdio_context is not None:
            await self.stdio_context.__aexit__(exc_type, exc, traceback)


def _extract_tools(response: Any) -> list[Any]:
    """从 session.list_tools() 的 response 中提取工具列表
    
    Args:
        response (Any): mcp SDK 一般返回对象, 这里兼容 dict
    
    Returns:
        list[Any]: 工具列表
    """
    if isinstance(response, dict):
        tools = response.get("tools", [])
    else:
        tools = getattr(response, "tools", [])
    return tools if isinstance(tools, list) else []


def _tool_to_dict(tool: Any) -> dict[str, Any]:
    """将工具对象转换为字典
    
    Args:
        tool (Any): 工具对象, 兼容 dict

    Returns:
        dict[str, Any]: 工具字典, 包含 name, description, input_schema
    """
    if isinstance(tool, dict):
        return {
            "name": tool.get("name", ""),
            "description": tool.get("description", ""),
            "input_schema": tool.get("inputSchema") or tool.get("input_schema") or {},
        }

    return {
        "name": getattr(tool, "name", ""),
        "description": getattr(tool, "description", ""),
        "input_schema": (
            getattr(tool, "inputSchema", None)
            or getattr(tool, "input_schema", None)
            or {}
        ),
    }


def _to_plain_data(value: Any) -> Any:
    """将任意对象转换为可序列化的纯数据结构
    
    Args:
        value (Any): session.call_tool() 返回的结果对象, 一般是 mcp.types.CallToolResult 对象 (有 model_dump 方法), 这里兼容其他类型

    Returns:
        Any: 可序列化的纯数据结构, 包含 dict, list, str
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, list):
        return [_to_plain_data(item) for item in value]

    if isinstance(value, tuple):
        return [_to_plain_data(item) for item in value]

    if isinstance(value, dict):
        return {str(key): _to_plain_data(item) for key, item in value.items()}

    if hasattr(value, "model_dump"):
        print(f"DEBUG: _to_plain_data: value={value}, type(value)={type(value)}")
        return _to_plain_data(value.model_dump())

    if hasattr(value, "dict"):
        return _to_plain_data(value.dict())

    if hasattr(value, "__dict__"):
        return {
            key: _to_plain_data(item)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }

    return str(value)


def _safe_error(exc: Exception) -> str:
    return str(exc) or exc.__class__.__name__
