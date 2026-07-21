from lulu_agent.storage.memory_store import MemoryStore
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
        )

    if action == "read":
        result = store.read()

    elif action == "add":
        result = store.add(args.get("kind", ""), args.get("content", ""))

    elif action == "update":
        result = store.update(args.get("id"), args.get("kind", ""), args.get("content", ""))

    elif action == "remove":
        result = store.remove(args.get("id"))

    return _memory_result(result)


def _memory_result(result: dict) -> ToolResult:
    if result.get("ok"):
        return ToolResult(ok=True, output=result)
    return ToolResult(ok=False, error=result.get("error", "Memory operation failed."))
