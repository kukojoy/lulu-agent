import json

from lulu_agent.assistant_response import StreamingAssistantResponseBuilder
from lulu_agent.config import config
from lulu_agent.context_manager import ContextManager
from lulu_agent.llm_client import LLMClient
from lulu_agent.events import (
    EVENT_ASSISTANT_DELTA,
    EVENT_ASSISTANT_MESSAGE,
    EVENT_ERROR,
    EVENT_MODEL_REQUEST,
    EVENT_TOOL_CALL,
    EVENT_TOOL_RESULT,
    EVENT_TURN_END,
    EVENT_TURN_START,
    EVENT_USER_MESSAGE,
    RuntimeEvent,
)
from lulu_agent.event_sinks import EventSink, NoopEventSink, new_turn_id
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
        event_sink: EventSink | None = None,
        max_turns: int = 10,
    ):
        self.llm_client = llm_client or LLMClient(config)
        self.tool_registry = tool_registry or create_tool_registry()
        self.context_manager = context_manager or ContextManager(memory_store=memory_store)
        self.session_store = session_store
        self.session_id = session_id
        self.event_sink = event_sink or NoopEventSink()
        self.max_turns = max_turns
        self.messages = self._load_or_initialize_messages()

    def run(self, user_input: str) -> str:
        turn_id = new_turn_id()
        self._emit(EVENT_TURN_START, turn_id)
        self._emit(EVENT_USER_MESSAGE, turn_id, content=user_input)
        self._append_user_message(user_input)

        for _ in range(self.max_turns):
            request_messages = self.context_manager.prepare_messages(self.messages)
            tool_schemas = self.tool_registry.schemas()
            self._emit(
                EVENT_MODEL_REQUEST,
                turn_id,
                message_count=len(request_messages),
                tool_count=len(tool_schemas),
            )
            message, streamed = self._request_assistant_message(
                request_messages,
                tool_schemas,
                turn_id,
            )
            tool_calls = message.tool_calls or []

            self._append_assistant_message(message)
            self._emit(
                EVENT_ASSISTANT_MESSAGE,
                turn_id,
                content=message.content or "",
                tool_call_count=len(tool_calls),
                final=not bool(tool_calls),
                streamed=streamed,
            )

            if not tool_calls:
                self._emit(EVENT_TURN_END, turn_id, status="completed")
                return message.content or ""

            for tool_call in tool_calls:
                self._append_tool_message(self._handle_tool_call(tool_call, turn_id))

        message = "Reached max turns before completing the task."
        self._emit(EVENT_ERROR, turn_id, message=message)
        self._emit(EVENT_TURN_END, turn_id, status="max_turns")
        return message

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

    def _handle_tool_call(self, tool_call, turn_id: str | None = None) -> dict:
        tool_name = tool_call.function.name
        args, parse_error = self._parse_tool_arguments(tool_call.function.arguments)
        turn_id = turn_id or new_turn_id()

        self._emit(
            EVENT_TOOL_CALL,
            turn_id,
            tool_call_id=tool_call.id,
            tool_name=tool_name,
            arguments=args,
        )
        result = parse_error or self.tool_registry.dispatch(tool_name, args)
        self._emit(
            EVENT_TOOL_RESULT,
            turn_id,
            tool_call_id=tool_call.id,
            tool_name=tool_name,
            ok=result.ok,
            output=result.output,
            error=result.error,
        )

        return {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": result.to_json(),
        }

    def _request_assistant_message(
        self,
        request_messages: list[dict],
        tool_schemas: list[dict],
        turn_id: str,
    ):
        if hasattr(self.llm_client, "stream_chat"):
            return self._stream_assistant_message(request_messages, tool_schemas, turn_id)

        response = self.llm_client.chat(
            messages=request_messages,
            tools=tool_schemas,
        )
        return response.choices[0].message, False

    def _stream_assistant_message(
        self,
        request_messages: list[dict],
        tool_schemas: list[dict],
        turn_id: str,
    ):
        stream = self.llm_client.stream_chat(
            messages=request_messages,
            tools=tool_schemas,
        )
        builder = StreamingAssistantResponseBuilder()
        for content_delta in builder.consume(stream):
            self._emit(
                EVENT_ASSISTANT_DELTA,
                turn_id,
                delta=content_delta,
            )

        response = builder.build()
        return response.message, response.streamed

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

    def _emit(self, event_type: str, turn_id: str, **payload) -> None:
        self.event_sink.emit(
            RuntimeEvent(
                type=event_type,
                turn_id=turn_id,
                payload=payload,
            )
        )
