import json

from lulu_agent.config import config
from lulu_agent.llm_client import LLMClient
from lulu_agent.tools import ToolRegistry, create_tool_registry


SYSTEM_PROMPT = """You are a local coding agent.
You can use tools to inspect files, write files, and run shell commands.
Use tools when needed.
Do not claim a command succeeded unless you saw the result.
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

    def run(self, user_input: str) -> str:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_input},
        ]

        for _ in range(self.max_turns):
            response = self.llm_client.chat(
                messages=messages,
                tools=self.tool_registry.schemas(),
            )
            message = response.choices[0].message
            tool_calls = message.tool_calls or []

            messages.append(self._assistant_message_to_dict(message))

            if not tool_calls:
                return message.content or ""

            for tool_call in tool_calls:
                args = json.loads(tool_call.function.arguments or "{}")
                print(f"[tool] {tool_call.function.name} args={args}")
                result = self.tool_registry.dispatch(tool_call.function.name, args)
                print(f"[tool result] ok={result.ok} output={result.output} error={result.error}")
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result.__dict__, ensure_ascii=False),
                    }
                )

        return "Reached max turns before completing the task."

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
