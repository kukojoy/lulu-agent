import subprocess

from lulu_agent.runtime.workspace import current_session_workspace
from lulu_agent.tools import ToolResult, tool, truncate_text
from lulu_agent.runtime.errors import (
    ERROR_INVALID_ARGUMENTS,
    ERROR_TIMEOUT,
)


MAX_SHELL_OUTPUT_CHARS = 4000
DEFAULT_SHELL_TIMEOUT_SECONDS = 30
MAX_SHELL_TIMEOUT_SECONDS = 600


@tool(
    name="run_shell",
    description="Run a shell command.",
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to run.",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds. Defaults to 30, max 600.",
            },
        },
        "required": ["command"],
    },
)
def run_shell(args):
    command = args["command"]
    cwd = current_session_workspace()
    timeout = args.get("timeout", DEFAULT_SHELL_TIMEOUT_SECONDS)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1:
        return ToolResult(
            ok=False,
            error="timeout must be an integer greater than or equal to 1.",
            error_type=ERROR_INVALID_ARGUMENTS,
        )
    timeout = min(timeout, MAX_SHELL_TIMEOUT_SECONDS)

    try:
        result = subprocess.run(
            command,
            shell=True,
            text=True,
            capture_output=True,
            timeout=timeout,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        stdout_result = truncate_text(stdout, MAX_SHELL_OUTPUT_CHARS)
        stderr_result = truncate_text(stderr, MAX_SHELL_OUTPUT_CHARS)
        output = {
            "cwd": str(cwd),
            "stdout": stdout_result,
            "stderr": stderr_result,
            "exit_code": None,
            "timeout": timeout,
        }
        return ToolResult(
            ok=False,
            output=output,
            error=f"Shell command timed out after {timeout} seconds.",
            error_type=ERROR_TIMEOUT,
            metadata=_metadata(stdout_result, stderr_result, timeout),
            truncated=stdout_result["truncated"] or stderr_result["truncated"],
        )

    stdout_result = truncate_text(result.stdout, MAX_SHELL_OUTPUT_CHARS)
    stderr_result = truncate_text(result.stderr, MAX_SHELL_OUTPUT_CHARS)
    return ToolResult(
        ok=result.returncode == 0,
        output={
            "cwd": str(cwd),
            "stdout": stdout_result,
            "stderr": stderr_result,
            "exit_code": result.returncode,
            "timeout": timeout,
        },
        metadata=_metadata(stdout_result, stderr_result, timeout),
        truncated=stdout_result["truncated"] or stderr_result["truncated"],
    )


def _metadata(stdout_result: dict, stderr_result: dict, timeout: int) -> dict:
    metadata = {
        "timeout": timeout,
        "stdout_original_length": stdout_result["original_length"],
        "stderr_original_length": stderr_result["original_length"],
    }
    truncated_streams = []
    if stdout_result["truncated"]:
        truncated_streams.append("stdout")
    if stderr_result["truncated"]:
        truncated_streams.append("stderr")
    if truncated_streams:
        metadata["truncated_streams"] = truncated_streams
    return metadata
