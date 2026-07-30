from pathlib import Path

from lulu_agent.runtime.safety import PATH_OPERATION_READ, PathSafetyError, validate_workspace_path
from lulu_agent.tools import ToolResult, tool
from lulu_agent.runtime.errors import (
    ERROR_EXTERNAL_TOOL,
    ERROR_INVALID_ARGUMENTS,
    ERROR_NOT_FOUND,
    ERROR_PERMISSION_DENIED,
)


DEFAULT_MAX_ENTRIES = 100
SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
}


@tool(
    name="list_files",
    description=(
        "List files and directories at a path. Use this to inspect directory "
        "contents instead of running ls in the shell."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File or directory path to list. Defaults to current directory.",
            },
            "recursive": {
                "type": "boolean",
                "description": "Whether to recursively list directory contents.",
            },
            "include_hidden": {
                "type": "boolean",
                "description": "Whether to include files and directories whose names start with '.'.",
            },
            "pattern": {
                "type": "string",
                "description": "Optional glob pattern to filter entries by name or relative path, such as '*.py', '**/*.md', or '*config*'.",
            },
            "max_entries": {
                "type": "integer",
                "description": "Maximum number of entries to return.",
            },
        },
    },
)
def list_files(args):
    try:
        path = validate_workspace_path(args.get("path") or ".", operation=PATH_OPERATION_READ)
    except PathSafetyError as exc:
        return ToolResult(ok=False, error=str(exc), error_type=ERROR_PERMISSION_DENIED)

    recursive = args.get("recursive", False)
    include_hidden = args.get("include_hidden", False)
    pattern = args.get("pattern")
    max_entries = args.get("max_entries", DEFAULT_MAX_ENTRIES)

    if not isinstance(recursive, bool):
        return ToolResult(ok=False, error="recursive must be a boolean.", error_type=ERROR_INVALID_ARGUMENTS)
    if not isinstance(include_hidden, bool):
        return ToolResult(ok=False, error="include_hidden must be a boolean.", error_type=ERROR_INVALID_ARGUMENTS)
    if pattern is not None and not isinstance(pattern, str):
        return ToolResult(ok=False, error="pattern must be a string.", error_type=ERROR_INVALID_ARGUMENTS)
    if isinstance(pattern, str) and not pattern.strip():
        pattern = None
    if not isinstance(max_entries, int) or isinstance(max_entries, bool) or max_entries < 1:
        return ToolResult(ok=False, error="max_entries must be at least 1.", error_type=ERROR_INVALID_ARGUMENTS)

    if not path.exists():
        return ToolResult(ok=False, error=f"Path not found: {path}", error_type=ERROR_NOT_FOUND)

    try:
        entries, truncated = _collect_entries(path, recursive, include_hidden, pattern, max_entries)
    except OSError as exc:
        return ToolResult(
            ok=False,
            error=f"Failed to list path {path}: {exc}",
            error_type=ERROR_EXTERNAL_TOOL,
        )

    output = {
        "path": str(path),
        "recursive": recursive,
        "entries": entries,
        "returned_count": len(entries),
        "truncated": truncated,
    }
    if pattern is not None:
        output["pattern"] = pattern
    if truncated:
        output["hint"] = "Narrow pattern or path, or increase max_entries to see more results."

    return ToolResult(
        ok=True,
        output=output,
        truncated=truncated,
    )


def _collect_entries(
    path: Path,
    recursive: bool,
    include_hidden: bool,
    pattern: str | None,
    max_entries: int,
) -> tuple[list[dict], bool]:
    if path.is_file():
        entries = [_entry_for_path(path)] if _matches_pattern(path, path.parent, pattern) else []
        return entries, False
    if not path.is_dir():
        entries = [_entry_for_path(path)] if _matches_pattern(path, path.parent, pattern) else []
        return entries, False

    iterator = _iter_children(path, recursive)
    entries = []
    for child in sorted(iterator, key=_sort_key):
        if not include_hidden and _is_hidden_relative_to(child, path):
            continue
        if not _matches_pattern(child, path, pattern):
            continue
        entries.append(_entry_for_path(child))
        if len(entries) > max_entries:
            break
    return entries[:max_entries], len(entries) > max_entries


def _iter_children(path: Path, recursive: bool):
    if not recursive:
        yield from path.iterdir()
        return

    for child in path.rglob("*"):
        if any(part in SKIP_DIR_NAMES for part in _relative_parts(child, path)):
            continue
        yield child


def _entry_for_path(path: Path) -> dict:
    entry = {
        "name": path.name,
        "path": str(path),
        "type": _path_type(path),
    }
    if path.is_file():
        entry["size"] = path.stat().st_size
    return entry


def _path_type(path: Path) -> str:
    if path.is_dir():
        return "directory"
    if path.is_file():
        return "file"
    return "other"


def _sort_key(path: Path) -> tuple[int, str]:
    return (0 if path.is_dir() else 1, str(path))


def _is_hidden_relative_to(path: Path, root: Path) -> bool:
    return any(part.startswith(".") for part in _relative_parts(path, root))


def _relative_parts(path: Path, root: Path) -> tuple[str, ...]:
    try:
        return path.relative_to(root).parts
    except ValueError:
        return path.parts


def _matches_pattern(path: Path, root: Path, pattern: str | None) -> bool:
    if pattern is None:
        return True
    relative = path.relative_to(root).as_posix() if _is_relative_to(path, root) else path.name
    return path.name == pattern or path.name.lower() == pattern.lower() or path.match(pattern) or Path(relative).match(pattern)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
