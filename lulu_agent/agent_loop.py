import json

from lulu_agent.config import config
from lulu_agent.context_manager import ContextManager
from lulu_agent.llm_client import LLMClient
from lulu_agent.session_store import SessionStore
from lulu_agent.tools import ToolRegistry, ToolResult, create_tool_registry


SYSTEM_PROMPT = """You are a local coding agent.
You can use tools to inspect files, write files, and run shell commands.
Use tools when needed.
You have a memory tool for durable long-term memory. Only write memory when the user explicitly asks you to remember, forget, or update durable preferences, facts, or project conventions. Do not store temporary task state, full chat logs, sensitive information, or unconfirmed guesses.
You have a skill tool for local workspace skills in .lulu/skills. Use skill list to inspect available skill metadata when the user mentions skills or when a task may need a specific stored procedure. Use skill read only for a specific relevant skill; do not read every skill by default. Skills are procedural instructions, not memory. Do not modify skill files unless the user explicitly asks.
Tools whose names start with mcp_ come from external MCP servers. Use their names and descriptions to judge when they are relevant, and do not assume external MCP tools are safe, stable, or always available. Do not write MCP configuration, server env values, or temporary MCP tool results to memory unless the user explicitly asks you to remember them.
Do not claim a command succeeded unless you saw the result.
For shell-based file operations, do not rely only on exit code. Check cwd and verify the target state with ls/test/find when needed.
When the task is complete, answer clearly and briefly."""


class AgentLoop:
    def __init__(
        self,
        llm_client: LLMClient | None = None,
        tool_registry: ToolRegistry | None = None,
        context_manager: ContextManager | None = None,
        memory_store=None,
        session_store: SessionStore | None = None,
        session_id: str | None = None,
        max_turns: int = 10,
    ):
        self.llm_client = llm_client or LLMClient(config)
        self.tool_registry = tool_registry or create_tool_registry()
        self.context_manager = context_manager or ContextManager(memory_store=memory_store)
        self.session_store = session_store
        self.session_id = session_id
        self.max_turns = max_turns
        self.messages = self._load_or_initialize_messages()

    def run(self, user_input: str) -> str:
        self._append_user_message(user_input)

        for _ in range(self.max_turns):
            request_messages = self.context_manager.prepare_messages(self.messages)
            response = self.llm_client.chat(
                messages=request_messages,
                tools=self.tool_registry.schemas(),
            )
            message = response.choices[0].message
            tool_calls = message.tool_calls or []

            self._append_assistant_message(message)

            if not tool_calls:
                return message.content or ""

            for tool_call in tool_calls:
                self._append_tool_message(self._handle_tool_call(tool_call))

        return "Reached max turns before completing the task."

    def _append_user_message(self, content: str) -> None:
        self._append_message({"role": "user", "content": content})

    def _append_assistant_message(self, message) -> None:
        self._append_message(self._assistant_message_to_dict(message))

    def _append_tool_message(self, message: dict) -> None:
        self._append_message(message)

    def _append_message(self, message: dict) -> None:
        self.messages.append(message)
        if self.session_store and self.session_id:
            self.session_store.append_message(self.session_id, message)

    def _load_or_initialize_messages(self) -> list[dict]:
        if self.session_store and self.session_id:
            messages = self.session_store.load_messages(self.session_id)
            if messages:
                return messages

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if self.session_store and self.session_id:
            self.session_store.append_message(self.session_id, messages[0])
        return messages

    def _handle_tool_call(self, tool_call) -> dict:
        tool_name = tool_call.function.name
        args, parse_error = self._parse_tool_arguments(tool_call.function.arguments)

        self._print_tool_call(tool_name, args)
        result = parse_error or self.tool_registry.dispatch(tool_name, args)
        self._print_tool_result(result)

        return {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": result.to_json(),
        }

    def _parse_tool_arguments(self, raw_arguments: str | None) -> tuple[dict, ToolResult | None]:
        if not raw_arguments:
            return {}, None

        try:
            args = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            return {}, ToolResult(
                ok=False,
                error=f"Invalid tool arguments JSON: {exc.msg}",
            )

        if not isinstance(args, dict):
            return {}, ToolResult(
                ok=False,
                error="Tool arguments must be a JSON object.",
            )

        return args, None

    def _print_tool_call(self, name: str, args: dict) -> None:
        print(f"[tool] {name} args={args}")

    def _print_tool_result(self, result: ToolResult) -> None:
        print(f"[tool result] ok={result.ok} output={result.output} error={result.error}")

    def _assistant_message_to_dict(self, message) -> dict:
        result = {
            "role": "assistant",
            "content": message.content,
        }

        if message.tool_calls:
            result["tool_calls"] = [
                {
                    "id": tool_call.id,
                    "type": tool_call.type,
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments,
                    },
                }
                for tool_call in message.tool_calls
            ]

        return result
