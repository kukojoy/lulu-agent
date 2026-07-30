from lulu_agent.runtime.safety import PATH_OPERATION_READ, PathSafetyError, validate_workspace_path
from lulu_agent.tools import ToolResult, tool
from lulu_agent.runtime.errors import (
    ERROR_EXTERNAL_TOOL,
    ERROR_INVALID_ARGUMENTS,
    ERROR_NOT_FOUND,
    ERROR_PERMISSION_DENIED,
)


DEFAULT_READ_OFFSET = 1
DEFAULT_READ_LIMIT = 500
MAX_READ_LIMIT = 2000
MAX_READ_CHARS = 100_000
MAX_LINE_LENGTH = 2000


@tool(
    name="read_file",
    description=(
        "Read a text file with line numbers and pagination. Use offset and "
        "limit for large files."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file.",
            },
            "offset": {
                "type": "integer",
                "description": "Line number to start reading from. Defaults to 1.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to read. Defaults to 500, max 2000.",
            },
        },
        "required": ["path"],
    },
)
def read_file(args):
    try:
        path = validate_workspace_path(args["path"], operation=PATH_OPERATION_READ)
    except PathSafetyError as exc:
        return ToolResult(ok=False, error=str(exc), error_type=ERROR_PERMISSION_DENIED)

    if not path.exists():
        return ToolResult(ok=False, error=f"File not found: {path}", error_type=ERROR_NOT_FOUND)
    if not path.is_file():
        return ToolResult(ok=False, error=f"Path is not a file: {path}", error_type=ERROR_INVALID_ARGUMENTS)

    offset = args.get("offset", DEFAULT_READ_OFFSET)
    limit = args.get("limit", DEFAULT_READ_LIMIT)
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 1:
        return ToolResult(
            ok=False,
            error="offset must be an integer greater than or equal to 1.",
            error_type=ERROR_INVALID_ARGUMENTS,
        )
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        return ToolResult(
            ok=False,
            error="limit must be an integer greater than or equal to 1.",
            error_type=ERROR_INVALID_ARGUMENTS,
        )
    limit = min(limit, MAX_READ_LIMIT)

    try:
        raw_content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return ToolResult(
            ok=False,
            error=f"Failed to read file {path}: {exc}",
            error_type=ERROR_EXTERNAL_TOOL,
        )

    lines = raw_content.splitlines()
    total_lines = len(lines)
    start_index = offset - 1
    requested_end_line = offset + limit - 1
    selected_lines = lines[start_index:requested_end_line]
    content, lines_kept, truncated_by_chars = _format_lines_with_budget(selected_lines, offset)
    end_line = offset + lines_kept - 1 if lines_kept else offset - 1
    truncated_by_lines = total_lines > requested_end_line
    truncated = truncated_by_lines or truncated_by_chars
    next_offset = end_line + 1 if truncated and end_line < total_lines else None

    output = {
        "path": str(path),
        "content": content,
        "offset": offset,
        "limit": limit,
        "start_line": offset if lines_kept else None,
        "end_line": end_line if lines_kept else None,
        "total_lines": total_lines,
        "truncated": truncated,
    }
    metadata = {
        "offset": offset,
        "limit": limit,
        "total_lines": total_lines,
        "returned_lines": lines_kept,
        "original_length": len(raw_content),
    }
    if next_offset is not None:
        output["next_offset"] = next_offset
        output["hint"] = f"Use offset={next_offset} to continue reading."
        metadata["next_offset"] = next_offset
    if truncated_by_chars:
        output["truncated_by"] = "chars"
        metadata["truncated_by"] = "chars"
    elif truncated_by_lines:
        output["truncated_by"] = "lines"
        metadata["truncated_by"] = "lines"

    return ToolResult(
        ok=True,
        output=output,
        metadata=metadata,
        truncated=truncated,
    )


def _format_lines_with_budget(lines: list[str], start_line: int) -> tuple[str, int, bool]:
    rendered = []
    total_chars = 0
    for index, line in enumerate(lines, start=start_line):
        line_text = _truncate_line(line)
        rendered_line = f"{index}|{line_text}"
        extra_chars = len(rendered_line) + (1 if rendered else 0)
        if total_chars + extra_chars > MAX_READ_CHARS:
            if not rendered:
                return rendered_line[:MAX_READ_CHARS], 1, True
            return "\n".join(rendered), len(rendered), True
        rendered.append(rendered_line)
        total_chars += extra_chars
    return "\n".join(rendered), len(rendered), False


def _truncate_line(line: str) -> str:
    if len(line) <= MAX_LINE_LENGTH:
        return line
    return f"{line[:MAX_LINE_LENGTH]}... [line truncated]"
