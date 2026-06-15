from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ToolResult:
    ok: bool
    output: Any = None
    error: str | None = None


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any]], ToolResult]

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool):
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    def dispatch(self, name: str, args: dict[str, Any]) -> ToolResult:
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(ok=False, error=f"Unknown tool: {name}")

        try:
            return tool.handler(args)
        except Exception as exc:
            return ToolResult(ok=False, error=str(exc))


def tool(name: str, description: str, parameters: dict[str, Any]):
    def decorator(handler: Callable[[dict[str, Any]], ToolResult]) -> Tool:
        return Tool(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
        )

    return decorator


def create_tool_registry() -> ToolRegistry:
    from lulu_agent.native_tools.read_file import read_file
    from lulu_agent.native_tools.run_shell import run_shell
    from lulu_agent.native_tools.write_file import write_file

    registry = ToolRegistry()
    registry.register(read_file)
    registry.register(write_file)
    registry.register(run_shell)
    return registry

