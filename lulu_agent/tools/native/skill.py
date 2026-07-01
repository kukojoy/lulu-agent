from dataclasses import asdict

from lulu_agent.skills.loader import SkillLoader, SkillLoaderError
from lulu_agent.tools import ToolResult, tool


@tool(
    name="skill",
    description=(
        "List or read local workspace skills from .lulu/skills. Use action=list "
        "to inspect available skill metadata first. Use action=read only when "
        "a specific skill is relevant or explicitly requested by the user. "
        "Do not read every skill by default."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "Skill action: list or read.",
            },
            "name": {
                "type": "string",
                "description": "Skill name. Required for read.",
            },
        },
        "required": ["action"],
    },
)
def skill(args):
    loader = SkillLoader()
    action = args["action"]

    if action == "list":
        result = loader.list_skills()
        return ToolResult(
            ok=True,
            output={
                "root": result.root,
                "skills": [asdict(skill) for skill in result.skills],
                "errors": [asdict(error) for error in result.errors],
            },
        )

    if action == "read":
        try:
            document = loader.read_skill(args.get("name", ""))
        except SkillLoaderError as exc:
            return ToolResult(ok=False, error=str(exc))

        return ToolResult(ok=True, output=asdict(document))

    return ToolResult(
        ok=False,
        error="Unknown skill action. Use one of: list, read.",
    )
