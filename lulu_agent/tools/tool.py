import json
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ToolResult:
    ok: bool
    output: Any = None
    error: str | None = None
    error_type: str | None = None
    metadata: dict[str, Any] | None = None
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        result = {
            "ok": self.ok,
            "output": self.output,
            "error": self.error,
        }
        if self.error_type is not None:
            result["error_type"] = self.error_type
        if self.metadata is not None:
            result["metadata"] = self.metadata
        if self.truncated:
            result["truncated"] = self.truncated
        return result

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


def tool(name: str, description: str, parameters: dict[str, Any]):
    def decorator(handler: Callable[[dict[str, Any]], ToolResult]) -> Tool:
        return Tool(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
        )

    return decorator
