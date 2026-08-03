from lulu_agent.safety.utils import resolve_path
from lulu_agent.tools import ToolResult, tool
from lulu_agent.runtime.errors import ERROR_EXTERNAL_TOOL


@tool(
    name="write_file",
    description="Write text content to a file.",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to write.",
            },
            "content": {
                "type": "string",
                "description": "Text content to write.",
            },
        },
        "required": ["path", "content"],
    },
)
def write_file(args):
    path = resolve_path(args["path"])

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args["content"], encoding="utf-8")
    except OSError as exc:
        return ToolResult(
            ok=False,
            error=f"Failed to write file {path}: {exc}",
            error_type=ERROR_EXTERNAL_TOOL,
        )

    return ToolResult(
        ok=True,
        output={
            "path": str(path),
            "content_length": len(args["content"]),
        },
    )
