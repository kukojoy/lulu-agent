import os
import threading

from datetime import datetime

from lulu_agent.config import config
from lulu_agent.context.compressor import compress_turns
from lulu_agent.context.manager import ContextManager
from lulu_agent.llm.client import LLMClient
from lulu_agent.llm.response import ModelRequest
from lulu_agent.runtime.events import (
    EVENT_ASSISTANT_DELTA,
    EVENT_ASSISTANT_MESSAGE,
    EVENT_MODEL_REQUEST,
    EVENT_TOOL_CALL,
    EVENT_TOOL_RESULT,
    EVENT_TURN_END,
    EVENT_TURN_START,
    EVENT_USER_MESSAGE,
    EventPayloadBuilder,
    RuntimeEvent,
)
from lulu_agent.runtime.event_sinks import EventSink, NoopEventSink, new_turn_id
from lulu_agent.runtime.errors import ERROR_APPROVAL_DENIED, LuluError
from lulu_agent.runtime.turn import TurnExitReason, TurnRuntime, TurnStatus
from lulu_agent.storage.session_store import SessionStore
from lulu_agent.tools import ToolRegistry, ToolResult, create_tool_registry
from lulu_agent.tools.runtime import ToolCall, ToolRuntime


SYSTEM_PROMPT = """You are a local coding agent.
You can use tools to inspect files, write files, and run shell commands.
Use tools when needed.
You have a memory tool for durable global long-term memory. Only write memory when the user explicitly asks you to remember, forget, or update durable cross-project preferences, facts, or habits. Do not store project instructions, temporary task state, full chat logs, sensitive information, or unconfirmed guesses. Project instructions belong in AGENTS.md and are injected separately when present.
You have a skill_lookup tool and a skill_manage tool for global skills in ~/.lulu/skills. Use skill_lookup list to inspect available skill metadata when the user mentions skills or when a task may need a specific stored procedure. Use skill_lookup read only for a specific relevant skill; do not read every skill by default. Skills are procedural instructions, not memory. Do not modify skill files unless the user explicitly asks.
Tools whose names start with mcp_ come from external MCP servers. Use their names and descriptions to judge when they are relevant, and do not assume external MCP tools are safe, stable, or always available. Do not write MCP configuration, server env values, or temporary MCP tool results to memory unless the user explicitly asks you to remember them.
For current, recent, or source-sensitive facts, use runtime_environment for relative dates, put the relevant date/year/entity/fact type in search queries, treat search snippets as leads, open trusted results when precision matters, and answer only from tool-supported evidence. For recent event status, first determine the current phase and latest completed events; if results only show schedules, previews, background, or stale facts, refine the query toward results/status/finished/latest/today before answering. If evidence is stale, conflicting, or incomplete, keep checking or state uncertainty instead of filling gaps.
Do not claim a command succeeded unless you saw the result.
For shell-based file operations, do not rely only on exit code. Check cwd and verify the target state with ls/test/find when needed.
When the task is complete, answer clearly and briefly."""

INTERRUPTED_MESSAGE = "Current turn interrupted. You can continue with a new message."
APPROVAL_DENIED_MESSAGE = (
    "Operation cancelled. You denied the required approval, so I will not try another way "
    "to perform the same operation."
)


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
        memory_reviewer=None,  # lulu_agent.memory.review.MemoryReviewer (NOTE: 此注释是为了防止循环 import)
        skill_reviewer=None,  # lulu_agent.skills.review.SkillReviewer (NOTE: 此注释是为了防止循环 import)
        max_turns: int = 30,
    ):
        self.llm_client = llm_client or LLMClient(config)
        self.tool_registry = tool_registry or create_tool_registry()
        self.tool_runtime = ToolRuntime(self.tool_registry)
        self.session_store = session_store
        self.session_id = session_id
        self.context_manager = context_manager or ContextManager(
            memory_store=memory_store,
            session_store=session_store,
            session_id=session_id,
        )
        self.event_sink = event_sink or NoopEventSink()
        self.memory_reviewer = memory_reviewer
        self.skill_reviewer = skill_reviewer
        self._turns_since_memory_review = 0
        self._turns_since_skill_review = 0
        self.max_turns = max_turns
        self.messages = self._load_or_initialize_messages()
        self.current_turn: TurnRuntime | None = None

    def run(self, user_input: str) -> str:
        self.current_turn = TurnRuntime(turn_id=new_turn_id())

        # === event emit ===
        self._emit(
            EVENT_TURN_START, 
            self.current_turn.turn_id, 
            EventPayloadBuilder.build_turn_start_payload()
        )
        self._emit(
            EVENT_USER_MESSAGE,
            self.current_turn.turn_id,
            EventPayloadBuilder.build_user_message_payload(user_input),
        )
        # === event emit ===

        self._append_user_message(user_input)

        try:
            self._compress_context()
            for _ in range(self.max_turns):
                request_messages = self.context_manager.prepare_messages(
                    self.messages,
                    context_blocks=[self._runtime_environment_context_block()],
                )
                tool_schemas = self.tool_registry.schemas()

                # === event emit and turn state update ===
                self.current_turn.start_model_request()
                self._emit(
                    EVENT_MODEL_REQUEST,
                    self.current_turn.turn_id,
                    EventPayloadBuilder.build_model_request_payload(
                        model=getattr(self.llm_client, "model", ""),
                        stream=True,
                        request_index=self.current_turn.model_calls,
                        messages=request_messages,
                        tools=tool_schemas,
                    ),
                )
                # === event emit and turn state update ===

                message, streamed, usage = self._request_assistant_message(request_messages, tool_schemas)
                tool_calls = message.tool_calls or []
                
                self._append_assistant_message(message)

                # === event emit and turn state update ===
                self.current_turn.record_model_usage(usage)
                self._emit(
                    EVENT_ASSISTANT_MESSAGE,
                    self.current_turn.turn_id,
                    EventPayloadBuilder.build_assistant_message_payload(
                        content=message.content or "",
                        tool_call_count=len(tool_calls),
                        final=not bool(tool_calls),
                        streamed=streamed,
                        usage=usage,
                    ),
                )
                # === event emit and turn state update ===

                if not tool_calls:
                    
                    # === event emit and turn state update ===
                    self.current_turn.complete(TurnExitReason.ASSISTANT_FINAL)
                    result = self._finalize_turn(message.content or "")
                    # === event emit and turn state update ===

                    return result.final_response
                    
                for tool_call in tool_calls:
                    tool_message, tool_result = self._handle_tool_call(tool_call)
                    self._append_tool_message(tool_message)
                    if not tool_result.ok and tool_result.error_type == ERROR_APPROVAL_DENIED:
                        self.current_turn.interrupt(
                            APPROVAL_DENIED_MESSAGE,
                            reason=TurnExitReason.APPROVAL_DENIED,
                            error_type=ERROR_APPROVAL_DENIED,
                        )
                        turn_result = self._finalize_turn(APPROVAL_DENIED_MESSAGE)
                        return turn_result.final_response

            message = "Reached max turns before completing the task."

            # === event emit and turn state update ===
            self.current_turn.fail(TurnExitReason.MAX_TURNS_EXHAUSTED, message)
            result = self._finalize_turn(message)
            # === event emit and turn state update ===

            return result.final_response
        except KeyboardInterrupt:

            # === event emit and turn state update ===
            self.current_turn.interrupt(INTERRUPTED_MESSAGE)
            result = self._finalize_turn(self.current_turn.error or INTERRUPTED_MESSAGE)
            # === event emit and turn state update ===

            return result.final_response
        except Exception as exc:
            reason = self._error_exit_reason()

            if isinstance(exc, LuluError):
                error_message, error_type = exc.error_message, exc.error_type
            else:
                error_message, error_type = str(exc), None

            # === event emit and turn state update ===
            self.current_turn.fail(reason, error_message, error_type=error_type)
            self._finalize_turn()
            # === event emit and turn state update ===
     
            raise

    # === 上下文压缩 ===
    def _compress_context(self) -> None:
        """在本轮首次 LLM 请求前, 尝试压缩历史 turn"""
        if not self.session_store or not self.session_id:
            return

        plan = self.context_manager.plan_context(self.messages)
        compress_turns(
            messages=self.messages,
            plan=plan,
            llm_client=self.llm_client,
            session_store=self.session_store,
            session_id=self.session_id,
        )

    # === runtime 环境 context block 注入 ===  
    def _runtime_environment_context_block(self) -> dict:
        turn = self._active_turn()
        
        now = datetime.now().astimezone()
        timezone_name = now.tzname() or str(now.tzinfo or "local")
        lines = [
            "Time:",
            f"- local_time: {now.isoformat(timespec='seconds')}",
            f"- timezone: {timezone_name}",
            "- relative_time_basis: Resolve relative dates and times against local_time unless the user specifies another date, time, or timezone.",
            "",
            "Session/Turn:",
            f"- session_id: {self.session_id or 'none'}",
            f"- turn_id: {turn.turn_id if turn else 'none'}",
            "",
            "Workspace:",
            f"- cwd: {os.getcwd()}",
        ]
        content = "\n".join(lines)
        return {"name": "runtime_environment", "content": content}
    
    # === LLM 请求 ===
    def _request_assistant_message(
        self,
        request_messages: list[dict],
        tool_schemas: list[dict],
    ):
        """请求 llm 消息, 支持流式响应 (默认) 和非流式响应"""
        turn = self._active_turn()

        def on_delta(content_delta: str) -> None:
            turn.start_streaming()
            self._emit(
                EVENT_ASSISTANT_DELTA,
                turn.turn_id,
                EventPayloadBuilder.build_assistant_delta_payload(content_delta),
            )

        stream = True
        response = self.llm_client.complete(
            ModelRequest(
                messages=request_messages,
                tools=tool_schemas,
                stream=stream,
            ),
            on_delta=on_delta,
        )
        return response.message, response.streamed, response.usage

    # === 消息加载/存储 ===
    def _load_or_initialize_messages(self) -> list[dict]:
        if self.session_store and self.session_id:
            messages = self.session_store.load_messages(self.session_id)
            if messages:
                return messages

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if self.session_store and self.session_id:
            self.session_store.append_message(self.session_id, messages[0])
        return messages
    
    def _append_message(self, message: dict) -> None:
        turn = self._active_turn()
        
        message["turn_id"] = turn.turn_id
        self.messages.append(message)
        if self.session_store and self.session_id:
            self.session_store.append_message(self.session_id, message, turn.turn_id)

    # === 用户消息处理 ===
    def _append_user_message(self, content: str) -> None:
        self._append_message({"role": "user", "content": content})

    # === AI 消息处理 ===
    def _append_assistant_message(self, message) -> None:
        self._append_message(self._assistant_message_to_dict(message))

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

    # === 工具消息处理 ===
    def _append_tool_message(self, message: dict) -> None:
        self._append_message(message)

    def _handle_tool_call(
        self,
        raw_tool_call,
    ) -> tuple[dict, ToolResult]:
        tool_call = self.tool_runtime.decode(raw_tool_call)
        turn = self._active_turn()
        
        # === event emit and turn state update ===
        turn.start_tool(tool_call.tool_name)
        self._emit(
            EVENT_TOOL_CALL,
            turn.turn_id,
            EventPayloadBuilder.build_tool_call_payload(
                tool_call_id=tool_call.tool_call_id,
                tool_name=tool_call.tool_name,
                arguments=tool_call.arguments,
            ),
        )
        # === event emit and turn state update ===

        check_result = self.tool_runtime.check(tool_call)
        if check_result is not None:
            result = check_result
        else:
            result = self.tool_runtime.run(self._tool_call_with_runtime_args(tool_call))

        # === event emit and turn state update ===
        self._emit(
            EVENT_TOOL_RESULT,
            turn.turn_id,
            EventPayloadBuilder.build_tool_result_payload(
                tool_call_id=tool_call.tool_call_id,
                tool_name=tool_call.tool_name,
                ok=result.ok,
                output=result.output,
                error=result.error,
                error_type=result.error_type,
                metadata=result.metadata,
                truncated=result.truncated,
            ),
        )
        turn.finish_tool()
        # === event emit and turn state update ===

        return {
            "role": "tool",
            "tool_call_id": tool_call.tool_call_id,
            "content": result.to_json(),
        }, result

    def _tool_call_with_runtime_args(self, tool_call: ToolCall) -> ToolCall:
        """必要时为特定工具添加 runtime 参数, 例如 session_store/session_id"""
        if tool_call.tool_name != "task_state":
            return tool_call
        arguments = dict(tool_call.arguments)
        arguments["_session_store"] = self.session_store
        arguments["_session_id"] = self.session_id
        return ToolCall(
            tool_call_id=tool_call.tool_call_id,
            tool_name=tool_call.tool_name,
            arguments=arguments,
            parse_error=tool_call.parse_error,
        )

    # === turn runtime ===
    def _finalize_turn(self, final_response: str = ""):
        turn = self._active_turn()
        turn_record = turn.to_record(final_response)
        if self.session_store and self.session_id:
            self.session_store.append_turn(self.session_id, turn_record)
        self._review_knowledge(turn_record)
        self._emit(
            EVENT_TURN_END,
            turn.turn_id,
            EventPayloadBuilder.build_turn_end_payload(
                status=turn_record.status,
                exit_reason=turn_record.exit_reason,
                error=turn_record.error,
                error_type=turn_record.error_type,
                model_calls=turn.model_calls,
                tool_calls=turn.tool_calls,
            ),
        )
        self.current_turn = None
        return turn_record

    def _review_knowledge(self, turn_record) -> None:
        """成功 turn 结束后启动后台 knowledge reviewers, 不污染主链路"""
        if turn_record.status != TurnStatus.COMPLETED or not turn_record.final_response:
            return

        reviewers = (
            ("memory-review", self.memory_reviewer, "_turns_since_memory_review"),
            ("skill-review", self.skill_reviewer, "_turns_since_skill_review"),
        )

        for thread_name, reviewer, counter in reviewers:
            if not reviewer:
                continue
            if reviewer.review_turns < 1:
                continue

            turns_since_review = getattr(self, counter) + 1
            if turns_since_review < reviewer.review_turns:
                setattr(self, counter, turns_since_review)
                continue

            setattr(self, counter, 0)
            messages_snapshot = [dict(message) for message in self.messages]

            def target(reviewer=reviewer, messages_snapshot=messages_snapshot):
                try:
                    reviewer.review(messages_snapshot)
                except Exception:
                    pass

            threading.Thread(target=target, daemon=True, name=thread_name).start()

    def _error_exit_reason(self):
        turn = self._active_turn()
        if turn.status == TurnStatus.STREAMING_ASSISTANT:
            return TurnExitReason.STREAM_ERROR
        if turn.status == TurnStatus.RUNNING_TOOL:
            return TurnExitReason.TOOL_ERROR
        if turn.status == TurnStatus.REQUESTING_MODEL:
            return TurnExitReason.MODEL_ERROR
        return TurnExitReason.UNKNOWN_ERROR

    def _active_turn(self) -> TurnRuntime:
        if self.current_turn is None:
            raise RuntimeError("AgentLoop has no active turn.")
        return self.current_turn

    # === 事件发送 ===
    def _emit(self, event_type: str, turn_id: str, payload: dict) -> None:
        self.event_sink.emit(
            RuntimeEvent(
                type=event_type,
                turn_id=turn_id,
                payload=payload,
            )
        )
