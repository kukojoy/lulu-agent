import subprocess

from lulu_agent.tools import ToolResult, tool


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
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
        },
    )

