import re
import subprocess
from pathlib import Path

from lulu_agent.tools import ToolResult, tool, truncate_text


MAX_SHELL_OUTPUT_CHARS = 4000
DANGEROUS_COMMAND_PATTERNS = [
    (re.compile(r"\brm\s+.*-[^\s]*r[^\s]*f"), "recursive forced delete"),
    (re.compile(r"\bsudo\b"), "sudo command"),
    (re.compile(r">\s*/(?:etc|bin|sbin|usr|var|System|Library)\b"), "redirect to system path"),
    (re.compile(r"\b(curl|wget)\b.*\|\s*(sh|bash)\b"), "download and execute shell script"),
]


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
    danger = detect_dangerous_command(command)
    if danger:
        return ToolResult(
            ok=False,
            error=f"Refused to run risky shell command: {danger}",
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


def detect_dangerous_command(command: str) -> str | None:
    for pattern, description in DANGEROUS_COMMAND_PATTERNS:
        if pattern.search(command):
            return description
    return None
