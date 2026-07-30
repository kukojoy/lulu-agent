import shutil
import subprocess
from pathlib import Path

from lulu_agent.runtime.safety import PATH_OPERATION_READ, PathSafetyError, validate_workspace_path
from lulu_agent.tools import ToolResult, tool
from lulu_agent.runtime.errors import (
    ERROR_EXTERNAL_TOOL,
    ERROR_INVALID_ARGUMENTS,
    ERROR_NOT_FOUND,
    ERROR_PERMISSION_DENIED,
    ERROR_TIMEOUT,
)


DEFAULT_SEARCH_LIMIT = 50
MAX_SEARCH_LIMIT = 200
MAX_MATCH_LINE_CHARS = 1000
SEARCH_TIMEOUT_SECONDS = 10
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
    name="search_text",
    description=(
        "Search literal text in local workspace files. Use this instead of "
        "running rg/grep in the shell when locating code, config, or error text."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Literal text to search for.",
            },
            "path": {
                "type": "string",
                "description": "File or directory path to search. Defaults to current directory.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of matches to return. Defaults to 50, max 200.",
            },
            "case_sensitive": {
                "type": "boolean",
                "description": "Whether matching is case-sensitive. Defaults to false.",
            },
        },
        "required": ["query"],
    },
)
def search_text(args):
    query = args["query"].strip()
    if not query:
        return ToolResult(ok=False, error="query must not be empty.", error_type=ERROR_INVALID_ARGUMENTS)

    try:
        path = validate_workspace_path(args.get("path") or ".", operation=PATH_OPERATION_READ)
    except PathSafetyError as exc:
        return ToolResult(ok=False, error=str(exc), error_type=ERROR_PERMISSION_DENIED)

    if not path.exists():
        return ToolResult(ok=False, error=f"Path not found: {path}", error_type=ERROR_NOT_FOUND)

    limit = args.get("limit", DEFAULT_SEARCH_LIMIT)
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        return ToolResult(
            ok=False,
            error="limit must be an integer greater than or equal to 1.",
            error_type=ERROR_INVALID_ARGUMENTS,
        )
    limit = min(limit, MAX_SEARCH_LIMIT)

    case_sensitive = args.get("case_sensitive", False)
    if not isinstance(case_sensitive, bool):
        return ToolResult(ok=False, error="case_sensitive must be a boolean.", error_type=ERROR_INVALID_ARGUMENTS)

    rg_path = shutil.which("rg")
    if rg_path:
        result = _search_with_rg(rg_path, path, query, limit, case_sensitive)
    else:
        result = _search_with_python(path, query, limit, case_sensitive)

    if not result.ok:
        return result

    result.output["path"] = str(path)
    result.output["query"] = query
    result.metadata = {
        "path": str(path),
        "query": query,
        "returned_count": result.output["returned_count"],
        "truncated": result.output["truncated"],
        "backend": result.output["backend"],
    }
    result.truncated = result.output["truncated"]
    return result


def _search_with_rg(
    rg_path: str,
    path: Path,
    query: str,
    limit: int,
    case_sensitive: bool,
) -> ToolResult:
    command = [
        rg_path,
        "--fixed-strings",
        "--line-number",
        "--no-heading",
        "--color",
        "never",
        "--",
        query,
        str(path),
    ]
    if not case_sensitive:
        command.insert(1, "--ignore-case")

    matches: list[dict] = []
    truncated = False
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert process.stdout is not None
        for line in process.stdout:
            match = _parse_rg_line(line)
            if not match:
                continue
            if len(matches) >= limit:
                truncated = True
                process.terminate()
                break
            matches.append(match)
        try:
            _, stderr = process.communicate(timeout=SEARCH_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            return ToolResult(
                ok=False,
                error=f"search_text timed out after {SEARCH_TIMEOUT_SECONDS} seconds.",
                error_type=ERROR_TIMEOUT,
            )
    except OSError as exc:
        return ToolResult(ok=False, error=f"Failed to run rg: {exc}", error_type=ERROR_EXTERNAL_TOOL)

    if process.returncode not in (0, 1, -15):
        return ToolResult(ok=False, error=f"rg search failed: {stderr.strip()}", error_type=ERROR_EXTERNAL_TOOL)

    return _search_result(matches, truncated=truncated, backend="rg")


def _search_with_python(path: Path, query: str, limit: int, case_sensitive: bool) -> ToolResult:
    needle = query if case_sensitive else query.lower()
    matches: list[dict] = []
    truncated = False

    for file_path in _iter_search_files(path):
        try:
            with file_path.open("r", encoding="utf-8", errors="replace") as handle:
                for line_number, line in enumerate(handle, start=1):
                    haystack = line if case_sensitive else line.lower()
                    if needle not in haystack:
                        continue
                    if len(matches) >= limit:
                        truncated = True
                        return _search_result(matches, truncated=truncated, backend="python")
                    matches.append(_match(file_path, line_number, line.rstrip("\n")))
        except OSError:
            continue

    return _search_result(matches, truncated=truncated, backend="python")


def _iter_search_files(path: Path):
    if path.is_file():
        if not _is_hidden(path):
            yield path
        return

    if not path.is_dir():
        return

    for child in sorted(path.rglob("*")):
        if child.is_dir():
            continue
        if _should_skip_path(child, root=path):
            continue
        yield child


def _should_skip_path(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        parts = path.parts
    return any(part.startswith(".") or part in SKIP_DIR_NAMES for part in parts)


def _is_hidden(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts)


def _parse_rg_line(line: str) -> dict | None:
    path_text, separator, rest = line.rstrip("\n").partition(":")
    if not separator:
        return None
    line_number_text, separator, text = rest.partition(":")
    if not separator:
        return None
    try:
        line_number = int(line_number_text)
    except ValueError:
        return None
    return _match(Path(path_text), line_number, text)


def _match(path: Path, line_number: int, text: str) -> dict:
    return {
        "path": str(path),
        "line": line_number,
        "text": _truncate_match_line(text),
    }


def _truncate_match_line(text: str) -> str:
    if len(text) <= MAX_MATCH_LINE_CHARS:
        return text
    return f"{text[:MAX_MATCH_LINE_CHARS]}... [line truncated]"


def _search_result(matches: list[dict], truncated: bool, backend: str) -> ToolResult:
    output = {
        "backend": backend,
        "matches": matches,
        "returned_count": len(matches),
        "truncated": truncated,
    }
    if truncated:
        output["hint"] = "Narrow the query or path, or increase limit to continue exploring."
    return ToolResult(ok=True, output=output, truncated=truncated)
