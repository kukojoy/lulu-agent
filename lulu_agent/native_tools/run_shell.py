import subprocess

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
    result = subprocess.run(
        args["command"],
        shell=True,
        text=True,
        capture_output=True,
    )
    return ToolResult(
        ok=result.returncode == 0,
        output={
            "stdout": truncate_text(result.stdout, MAX_SHELL_OUTPUT_CHARS),
            "stderr": truncate_text(result.stderr, MAX_SHELL_OUTPUT_CHARS),
            "exit_code": result.returncode,
        },
    )
