import json
from dataclasses import dataclass
from typing import Any, Callable


JSON_TYPE_CHECKS = {
    "array": list,
    "boolean": bool,
    "integer": int,
    "number": (int, float),
    "object": dict,
    "string": str,
}

DEFAULT_MAX_TEXT_CHARS = 4000


@dataclass
class ToolResult:
    ok: bool
    output: Any = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "output": self.output,
            "error": self.error,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


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

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    def dispatch(self, name: str, args: dict[str, Any]) -> ToolResult:
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(ok=False, error=f"Unknown tool: {name}")

        validation_error = validate_tool_args(tool, args)
        if validation_error:
            return ToolResult(ok=False, error=validation_error)

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


def validate_tool_args(tool: Tool, args: dict[str, Any]) -> str | None:
    parameters = tool.parameters
    required = parameters.get("required", [])
    properties = parameters.get("properties", {})

    for name in required:
        if name not in args:
            return f"Missing required argument '{name}' for tool '{tool.name}'."

    for name, value in args.items():
        schema = properties.get(name)
        if not schema:
            continue

        expected_type = schema.get("type")
        if not expected_type:
            continue

        if not _matches_json_type(value, expected_type):
            return (
                f"Invalid argument '{name}' for tool '{tool.name}': "
                f"expected {expected_type}, got {_json_type_name(value)}."
            )

    return None


def truncate_text(text: str, max_chars: int = DEFAULT_MAX_TEXT_CHARS) -> dict[str, Any]:
    original_length = len(text)
    truncated = original_length > max_chars
    return {
        "text": text[:max_chars] if truncated else text,
        "truncated": truncated,
        "original_length": original_length,
    }


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


def create_tool_registry() -> ToolRegistry:
    from lulu_agent.native_tools.list_files import list_files
    from lulu_agent.native_tools.memory import memory
    from lulu_agent.native_tools.read_file import read_file
    from lulu_agent.native_tools.replace_in_file import replace_in_file
    from lulu_agent.native_tools.run_shell import run_shell
    from lulu_agent.native_tools.write_file import write_file

    registry = ToolRegistry()
    registry.register(read_file)
    registry.register(write_file)
    registry.register(run_shell)
    registry.register(list_files)
    registry.register(replace_in_file)
    registry.register(memory)
    return registry
