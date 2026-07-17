import subprocess
from pathlib import Path

from lulu_agent.runtime.approval import request_cli_approval
from lulu_agent.runtime.safety import SAFETY_DENY, SAFETY_NEEDS_APPROVAL, classify_shell_command
from lulu_agent.tools import ToolResult, tool, truncate_text
from lulu_agent.tools.runtime import ERROR_TIMEOUT


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
    timeout = args.get("timeout", DEFAULT_SHELL_TIMEOUT_SECONDS)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1:
        return ToolResult(ok=False, error="timeout must be an integer greater than or equal to 1.")
    timeout = min(timeout, MAX_SHELL_TIMEOUT_SECONDS)

    decision = classify_shell_command(command)
    if decision.decision == SAFETY_DENY:
        return ToolResult(
            ok=False,
            error=f"Refused to run risky shell command: {decision.reason}",
        )

    if decision.decision == SAFETY_NEEDS_APPROVAL and not request_cli_approval(decision, command):
        return ToolResult(
            ok=False,
            error=f"Shell command requires approval and was denied: {decision.reason}",
        )

    try:
        result = subprocess.run(
            command,
            shell=True,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        stdout_result = truncate_text(stdout, MAX_SHELL_OUTPUT_CHARS)
        stderr_result = truncate_text(stderr, MAX_SHELL_OUTPUT_CHARS)
        output = {
            "cwd": str(Path.cwd()),
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
            "cwd": str(Path.cwd()),
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
