import json

from lulu_agent.config import config
from lulu_agent.llm_client import LLMClient
from lulu_agent.tools import ToolRegistry, ToolResult, create_tool_registry


SYSTEM_PROMPT = """You are a local coding agent.
You can use tools to inspect files, write files, and run shell commands.
Use tools when needed.
Do not claim a command succeeded unless you saw the result.
For shell-based file operations, do not rely only on exit code. Check cwd and verify the target state with ls/test/find when needed.
When the task is complete, answer clearly and briefly."""


class AgentLoop:
    def __init__(
        self,
        llm_client: LLMClient | None = None,
        tool_registry: ToolRegistry | None = None,
        max_turns: int = 10,
    ):
        self.llm_client = llm_client or LLMClient(config)
        self.tool_registry = tool_registry or create_tool_registry()
        self.max_turns = max_turns
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    def run(self, user_input: str) -> str:
        self._append_user_message(user_input)

        for _ in range(self.max_turns):
            response = self.llm_client.chat(
                messages=self.messages,
                tools=self.tool_registry.schemas(),
            )
            message = response.choices[0].message
            tool_calls = message.tool_calls or []

            self._append_assistant_message(message)

            if not tool_calls:
                return message.content or ""

            for tool_call in tool_calls:
                self.messages.append(self._handle_tool_call(tool_call))

        return "Reached max turns before completing the task."

    def _append_user_message(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content})

    def _append_assistant_message(self, message) -> None:
        self.messages.append(self._assistant_message_to_dict(message))

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
