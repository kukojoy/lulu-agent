import subprocess
from pathlib import Path

from lulu_agent.runtime.approval import request_cli_approval
from lulu_agent.runtime.safety import SAFETY_DENY, SAFETY_NEEDS_APPROVAL, classify_shell_command
from lulu_agent.tools import ToolResult, tool, truncate_text


MAX_SHELL_OUTPUT_CHARS = 4000


@tool(
    name="run_shell",
    description="Run a shell command.",
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to run.",
            }
        },
        "required": ["command"],
    },
)
def run_shell(args):
    command = args["command"]
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

    result = subprocess.run(
        command,
        shell=True,
        text=True,
        capture_output=True,
    )
    return ToolResult(
        ok=result.returncode == 0,
        output={
            "cwd": str(Path.cwd()),
            "stdout": truncate_text(result.stdout, MAX_SHELL_OUTPUT_CHARS),
            "stderr": truncate_text(result.stderr, MAX_SHELL_OUTPUT_CHARS),
            "exit_code": result.returncode,
        },
    )


def detect_dangerous_command(command: str):
    return classify_shell_command(command)
