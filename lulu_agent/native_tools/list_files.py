from pathlib import Path

from lulu_agent.tools import ToolResult, tool


DEFAULT_MAX_ENTRIES = 100


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
            "max_entries": {
                "type": "integer",
                "description": "Maximum number of entries to return.",
            },
        },
    },
)
def list_files(args):
    path = Path(args.get("path") or ".").resolve()
    recursive = args.get("recursive", False)
    include_hidden = args.get("include_hidden", False)
    max_entries = args.get("max_entries", DEFAULT_MAX_ENTRIES)

    if max_entries < 1:
        return ToolResult(ok=False, error="max_entries must be at least 1.")

    if not path.exists():
        return ToolResult(ok=False, error=f"Path not found: {path}")

    try:
        entries = _collect_entries(path, recursive, include_hidden, max_entries)
    except OSError as exc:
        return ToolResult(ok=False, error=f"Failed to list path {path}: {exc}")

    return ToolResult(
        ok=True,
        output={
            "path": str(path),
            "recursive": recursive,
            "entries": entries,
            "returned_count": len(entries),
            "truncated": _is_truncated(path, recursive, include_hidden, len(entries), max_entries),
        },
    )


def _collect_entries(
    path: Path,
    recursive: bool,
    include_hidden: bool,
    max_entries: int,
) -> list[dict]:
    if path.is_file():
        return [_entry_for_path(path)]
    if not path.is_dir():
        return [_entry_for_path(path)]

    iterator = path.rglob("*") if recursive else path.iterdir()
    entries = []
    for child in sorted(iterator, key=_sort_key):
        if not include_hidden and _is_hidden_relative_to(child, path):
            continue
        entries.append(_entry_for_path(child))
        if len(entries) >= max_entries:
            break
    return entries


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
    try:
        relative_parts = path.relative_to(root).parts
    except ValueError:
        relative_parts = path.parts
    return any(part.startswith(".") for part in relative_parts)


def _is_truncated(
    path: Path,
    recursive: bool,
    include_hidden: bool,
    returned_count: int,
    max_entries: int,
) -> bool:
    if returned_count < max_entries:
        return False
    if path.is_file() or not path.is_dir():
        return False

    iterator = path.rglob("*") if recursive else path.iterdir()
    seen = 0
    for child in iterator:
        if not include_hidden and _is_hidden_relative_to(child, path):
            continue
        seen += 1
        if seen > returned_count:
            return True
    return False
