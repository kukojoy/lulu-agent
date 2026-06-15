from pathlib import Path

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
    path = Path(args["path"])
    content = path.read_text(encoding="utf-8")
    return ToolResult(ok=True, output=content)

