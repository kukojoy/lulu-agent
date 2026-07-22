from lulu_agent.skills.store import SkillStoreError, SkillStore
from lulu_agent.tools import ToolResult, tool


@tool(
    name="skill_manage",
    description=(
        "Create, update, or patch global skills in ~/.lulu/skills. Use "
        "action=create with name and description to initialize a stable "
        "SKILL.md template; do not pass full body content to create. Use "
        "action=update to fully replace an existing SKILL.md, and "
        "action=patch to replace a unique exact substring in an existing "
        "SKILL.md. Use action=write_file and action=remove_file only for "
        "files under references/, templates/, or scripts/. Do not use it for "
        "read-only inspection."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "update", "patch", "write_file", "remove_file"],
                "description": "Skill management action.",
            },
            "name": {
                "type": "string",
                "description": "Skill name.",
            },
            "description": {
                "type": "string",
                "description": "Skill description. Required for create.",
            },
            "content": {
                "type": "string",
                "description": "Full SKILL.md content for update.",
            },
            "old_text": {
                "type": "string",
                "description": "Exact text to replace for patch.",
            },
            "new_text": {
                "type": "string",
                "description": "Replacement text for patch.",
            },
            "file_path": {
                "type": "string",
                "description": "Relative support file path for write_file/remove_file.",
            },
            "file_content": {
                "type": "string",
                "description": "Support file content for write_file.",
            },
        },
        "required": ["action", "name"],
    },
)
def skill_manage(args):
    store = SkillStore()
    action = args["action"]
    name = args["name"]

    try:
        if action == "create":
            if args.get("content", ""):
                return ToolResult(
                    ok=False,
                    error="content is not supported for create. Use description to create a template, then update or patch.",
                )
            description = args.get("description", "")
            if not description:
                return ToolResult(ok=False, error="description is required for create.")
            result = store.create_skill(name, description)

        elif action == "update":
            content = args.get("content", "")
            if not content:
                return ToolResult(ok=False, error="content is required for update.")
            result = store.update_skill(name, content)

        elif action == "patch":
            old_text = args.get("old_text", "")
            new_text = args.get("new_text", "")
            if not old_text:
                return ToolResult(ok=False, error="old_text is required for patch.")
            if new_text == "":
                return ToolResult(ok=False, error="new_text is required for patch.")
            result = store.patch_skill(name, old_text, new_text)

        elif action == "write_file":
            file_path = args.get("file_path", "")
            file_content = args.get("file_content", "")
            if not file_path:
                return ToolResult(ok=False, error="file_path is required for write_file.")
            if file_content == "":
                return ToolResult(ok=False, error="file_content is required for write_file.")
            result = store.write_file(name, file_path, file_content)

        elif action == "remove_file":
            file_path = args.get("file_path", "")
            if not file_path:
                return ToolResult(ok=False, error="file_path is required for remove_file.")
            result = store.remove_file(name, file_path)

        else:
            return ToolResult(
                ok=False,
                error="Unknown skill_manage action. Use one of: create, update, patch, write_file, remove_file.",
            )

    except SkillStoreError as exc:
        return ToolResult(ok=False, error=str(exc))
    except OSError as exc:
        return ToolResult(ok=False, error=f"Failed to manage skill: {exc}")

    if action == "remove_file":
        output = result.to_dict(("name", "path"))
    else:
        output = result.to_dict(("name", "path", "content_length"))

    return ToolResult(
        ok=True,
        output=output,
    )
