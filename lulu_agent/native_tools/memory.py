from lulu_agent.memory_store import MemoryStore
from lulu_agent.tools import ToolResult, tool


@tool(
    name="memory",
    description=(
        "Read or update long-term memory in MEMORY.md. Only use add, replace, "
        "or remove when the user explicitly asks to remember, forget, or update "
        "durable preferences, facts, or project conventions. Do not store "
        "temporary task state, full chat logs, sensitive information, or "
        "unconfirmed guesses. replace and remove operate on the entire memory "
        "entry identified by old_text; old_text is only a unique substring locator."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "Memory action: read, add, replace, or remove.",
            },
            "content": {
                "type": "string",
                "description": "Memory entry content. Required for add and replace.",
            },
            "old_text": {
                "type": "string",
                "description": "Unique substring identifying the entry to replace or remove.",
            },
        },
        "required": ["action"],
    },
)
def memory(args):
    store = MemoryStore()
    action = args["action"]
    if action not in {"read", "add", "replace", "remove"}:
        return ToolResult(
            ok=False,
            error="Unknown memory action. Use one of: read, add, replace, remove.",
        )

    if action == "read":
        result = store.read()

    elif action == "add":
        result = store.add(args.get("content", ""))

    elif action == "replace":
        result = store.replace(args.get("old_text", ""), args.get("content", ""))

    elif action == "remove":
        result = store.remove(args.get("old_text", ""))

    return _memory_result(result)


def _memory_result(result: dict) -> ToolResult:
    if result.get("ok"):
        return ToolResult(ok=True, output=result)
    return ToolResult(ok=False, error=result.get("error", "Memory operation failed."))
