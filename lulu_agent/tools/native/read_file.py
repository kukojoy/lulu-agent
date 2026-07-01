from lulu_agent.runtime.safety import PATH_OPERATION_READ, PathSafetyError, validate_workspace_path
from lulu_agent.tools import ToolResult, tool


@tool(
    name="read_file",
    description="Read a text file.",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file.",
            }
        },
        "required": ["path"],
    },
)
def read_file(args):
    try:
        path = validate_workspace_path(args["path"], operation=PATH_OPERATION_READ)
    except PathSafetyError as exc:
        return ToolResult(ok=False, error=str(exc))

    if not path.exists():
        return ToolResult(ok=False, error=f"File not found: {path}")
    if not path.is_file():
        return ToolResult(ok=False, error=f"Path is not a file: {path}")

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return ToolResult(ok=False, error=f"Failed to read file {path}: {exc}")

    return ToolResult(
        ok=True,
        output={
            "path": str(path),
            "content": content,
        },
    )
