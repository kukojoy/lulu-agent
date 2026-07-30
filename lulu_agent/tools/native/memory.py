from lulu_agent.runtime.errors import ERROR_EXTERNAL_TOOL, ERROR_INVALID_ARGUMENTS
from lulu_agent.storage.memory_store import MemoryResult, MemoryStore, MemoryStoreError
from lulu_agent.tools import ToolResult, tool


@tool(
    name="memory",
    description=(
        "Read or update global long-term memory in ~/.lulu/memory/MEMORY.md. "
        "Only use add, update, or remove when the user explicitly asks to "
        "remember, forget, or update durable cross-project preferences, facts, "
        "or habits. Do not store project instructions, temporary task state, "
        "full chat logs, sensitive information, or unconfirmed guesses. Project "
        "instructions belong in AGENTS.md and are not managed by this tool. "
        "Use kind=preference for user preferences, habits, and stable working "
        "style; use kind=fact for durable factual information. The tool assigns "
        "ids and updated_at values. update and remove operate by id."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["read", "add", "update", "remove"],
                "description": "Memory action: read, add, update, or remove.",
            },
            "id": {
                "type": "integer",
                "description": "Memory entry id. Required for update and remove.",
            },
            "kind": {
                "type": "string",
                "enum": ["preference", "fact"],
                "description": "Memory kind. Required for add and update.",
            },
            "content": {
                "type": "string",
                "description": "Memory entry content. Required for add and update.",
            },
        },
        "required": ["action"],
    },
)
def memory(args):
    store = MemoryStore()
    action = args["action"]
    if action not in {"read", "add", "update", "remove"}:
        return ToolResult(
            ok=False,
            error="Unknown memory action. Use one of: read, add, update, remove.",
            error_type=ERROR_INVALID_ARGUMENTS,
        )

    try:
        if action == "read":
            result = store.read()
        elif action == "add":
            result = store.add(args.get("kind", ""), args.get("content", ""))
        elif action == "update":
            result = store.update(args.get("id"), args.get("kind", ""), args.get("content", ""))
        else:
            result = store.remove(args.get("id"))
    except MemoryStoreError as exc:
        return ToolResult(ok=False, error=exc.error_message, error_type=exc.error_type)
    except OSError as exc:
        return ToolResult(ok=False, error=f"Memory operation failed: {exc}", error_type=ERROR_EXTERNAL_TOOL)

    if not isinstance(result, MemoryResult):
        return ToolResult(ok=False, error="Memory operation failed.", error_type=ERROR_EXTERNAL_TOOL)

    if action == "read":
        output = result.to_dict(("path", "content", "entries", "truncated", "original_length"))
    else:
        output = result.to_dict(("message", "path", "entry"))

    return ToolResult(ok=True, output=output)
