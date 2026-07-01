from lulu_agent.runtime.safety import PATH_OPERATION_WRITE, PathSafetyError, validate_workspace_path
from lulu_agent.tools import ToolResult, tool


@tool(
    name="replace_in_file",
    description=(
        "Replace exact text in a single file. Use this for small targeted edits "
        "after reading the file. The old_string must match file contents exactly; "
        "by default it must match exactly once."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to edit.",
            },
            "old_string": {
                "type": "string",
                "description": "Exact text to replace. Must be unique unless replace_all is true.",
            },
            "new_string": {
                "type": "string",
                "description": "Replacement text.",
            },
            "replace_all": {
                "type": "boolean",
                "description": "Replace all occurrences instead of requiring a unique match.",
            },
        },
        "required": ["path", "old_string", "new_string"],
    },
)
def replace_in_file(args):
    try:
        path = validate_workspace_path(args["path"], operation=PATH_OPERATION_WRITE)
    except PathSafetyError as exc:
        return ToolResult(ok=False, error=str(exc))

    old_string = args["old_string"]
    new_string = args["new_string"]
    replace_all = args.get("replace_all", False)

    if old_string == "":
        return ToolResult(
            ok=False,
            error="old_string must not be empty. Use write_file to create or rewrite files.",
        )
    if old_string == new_string:
        return ToolResult(ok=False, error="old_string and new_string are identical; no changes made.")

    if not path.exists():
        return ToolResult(ok=False, error=f"File not found: {path}")
    if not path.is_file():
        return ToolResult(ok=False, error=f"Path is not a file: {path}")

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return ToolResult(ok=False, error=f"Failed to read file {path}: {exc}")

    count = content.count(old_string)
    if count == 0:
        return ToolResult(
            ok=False,
            error=f"old_string not found in {path}. Read the file and provide exact surrounding context.",
        )
    if count > 1 and not replace_all:
        return ToolResult(
            ok=False,
            error=(
                f"old_string appears {count} times in {path}; "
                "provide more context or set replace_all=true."
            ),
        )

    new_content = content.replace(old_string, new_string) if replace_all else content.replace(old_string, new_string, 1)

    try:
        path.write_text(new_content, encoding="utf-8")
    except OSError as exc:
        return ToolResult(ok=False, error=f"Failed to write file {path}: {exc}")

    return ToolResult(
        ok=True,
        output={
            "path": str(path),
            "replacements": count if replace_all else 1,
            "content_length": len(new_content),
        },
    )
