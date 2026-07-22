from dataclasses import asdict

from lulu_agent.skills.store import SkillStoreError, SkillStore
from lulu_agent.tools import ToolResult, tool


@tool(
    name="skill_lookup",
    description=(
        "List or read global skills from ~/.lulu/skills. Use action=list to "
        "inspect available skill metadata first. Use action=read only when a "
        "specific skill is relevant or explicitly requested by the user. Do "
        "not read every skill by default."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "read"],
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
def skill_lookup(args):
    store = SkillStore()
    action = args["action"]

    if action == "list":
        result = store.list_skills()
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
            document = store.read_skill(args.get("name", ""))
        except SkillStoreError as exc:
            return ToolResult(ok=False, error=str(exc))

        return ToolResult(
            ok=True,
            output=document.to_dict(
                ("name", "description", "path", "directory", "content")
            ),
        )

    return ToolResult(
        ok=False,
        error="Unknown skill action. Use one of: list, read.",
    )
