from __future__ import annotations

import json

from lulu_agent.llm.client import LLMClient
from lulu_agent.context.manager import ContextManager
from lulu_agent.core.agent_loop import AgentLoop
from lulu_agent.memory.store import MemoryStore
from lulu_agent.runtime.message import Message
from lulu_agent.reviewers.base import BaseReviewer, BaseReviewResult, ReviewerType
from lulu_agent.tools import ToolRegistry
from lulu_agent.tools.native.memory import memory
from lulu_agent.skills.store import SkillStore


MEMORY_REVIEW_PROMPT = """Audit and maintain global long-term memory using the recent conversation and existing memory.

Use the memory tool only for durable cross-session user preferences or facts.
Always call memory read first. Do not answer Nothing to save before inspecting current memory entries.

Allowed maintenance patterns:
- add candidate: add a new durable preference or fact clearly supported by the conversation.
- merge: update one primary entry to contain the combined durable meaning, then remove redundant entries.
- refine: update an entry when the conversation or existing memory supports a clearer, more compact, or more accurate version.
- prune: remove duplicate, stale, temporary, overly narrow, or low-value entries.

Memory quality rules:
- Prefer compact consolidated memories over many tiny overlapping entries.
- Merge entries that share the same subject and category when a single entry would be clearer.
- Split only when entries are about different subjects or materially different categories.
- Correct obvious kind mistakes when refining, such as identity or biographical facts stored as preferences.

Do not store project instructions, temporary task state, full chat logs, secrets, or unconfirmed guesses.
If nothing should be added, merged, refined, or pruned, answer exactly: Nothing to save."""


class MemoryReviewResult(BaseReviewResult):
    pass


class MemoryReviewer(BaseReviewer):
    def __init__(
        self,
        memory_store: MemoryStore | None = None,
        max_turns: int = 20,
        review_turns: int = 8,
    ):
        self.type = ReviewerType.MEMORY
        self.memory_store = memory_store or MemoryStore()
        self.max_turns = max_turns
        self.review_turns = review_turns

    def review(self, messages_snapshot: list[Message], llm_client: LLMClient) -> MemoryReviewResult:
        """后台检查对话是否需要更新 memory, 不污染主链路 messages/session"""
        sub_agent = AgentLoop(
            llm_client=llm_client,
            tool_registry=_memory_only_registry(),
            context_manager=ContextManager(
                memory_store=self.memory_store,
                skill_store=SkillStore(".lulu/skills_empty"),  # NOTE: 需保证路径 ".lulu/skills_empty" 不存在或为空目录
            ),
            max_turns=self.max_turns,
        )
        sub_agent.messages = [
            Message(role="system", content=MEMORY_REVIEW_PROMPT),
            *_recent_turn_messages(messages_snapshot, self.review_turns),
        ]
        review_start = len(sub_agent.messages)
        response = sub_agent.run(
            "Read current memory, then audit recent conversation and existing entries. "
            "Use memory add/update/remove to add candidates, merge overlaps, refine unclear entries, or prune low-value entries. "
            "Only answer Nothing to save after reading memory and deciding no operation is useful."
        )

        review_messages = sub_agent.messages[review_start:]
        tool_calls = _get_tool_calls(review_messages)
        tool_results = _get_tool_results(review_messages)
        summaries = _get_summaries(tool_calls, tool_results)

        return MemoryReviewResult(
            response=response,
            summaries=summaries
        )


def _memory_only_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(memory)
    return registry


def _recent_turn_messages(messages: list[Message], recent_turns: int) -> list[Message]:
    turn_ids = []
    for message in messages:
        turn_id = message.turn_id
        if turn_id and turn_id not in turn_ids:
            turn_ids.append(turn_id)

    selected_turn_ids = set(turn_ids[-recent_turns:])
    selected = []
    for message in messages:
        if message.role == "system":
            continue
        if selected_turn_ids and message.turn_id not in selected_turn_ids:
            continue
        selected.append(message)
    return selected


def _get_tool_calls(messages: list[Message]) -> list[dict]:
    """从 messages 中提取所有工具调用记录"""
    tool_call_records = []
    for message in messages:
        if message.role != "assistant":
            continue
        tool_calls = message.tool_calls
        if not isinstance(tool_calls, list):
            continue
        tool_call_records.extend(tool_call for tool_call in tool_calls if isinstance(tool_call, dict))
    return tool_call_records


def _get_tool_results(messages: list[Message]) -> dict[str, dict]:
    """从 messages 中提取所有工具调用结果
    
    Returns:
        dict[str, dict]: tool_call_id -> tool_result
    """
    tool_results = {}
    for message in messages:
        if message.role != "tool":
            continue
        tool_call_id = message.tool_call_id
        content = message.content
        if not isinstance(tool_call_id, str) or not isinstance(content, str):
            continue
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            continue
        if isinstance(result, dict) and result.get("ok") is True:
            tool_results[tool_call_id] = result
    return tool_results


def _get_summaries(tool_calls: list[dict], tool_results: dict[str, dict]) -> list[str]:
    """从 tool_calls 中提取已完成的 memory 操作, 并生成摘要"""
    summaries = []
    for tool_call in tool_calls:
        tool_call_id = tool_call.get("id")
        if tool_call_id not in tool_results or tool_call.get("function", {}).get("name") != "memory":
            continue

        arguments = tool_call.get("function", {}).get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                continue
        if not isinstance(arguments, dict):
            continue
        action = arguments.get("action")
        if action not in {"add", "update", "remove"}:
            continue

        tool_result = tool_results[tool_call_id]
        output = tool_result.get("output") if isinstance(tool_result.get("output"), dict) else {}
        entry = output.get("entry") if isinstance(output.get("entry"), dict) else {}
        entry_id = entry.get("id") or arguments.get("id")
        if action == "add":
            summaries.append(_format_memory_change("added memory", entry_id))
        elif action == "update":
            summaries.append(_format_memory_change("updated memory", entry_id))
        elif action == "remove":
            summaries.append(_format_memory_change("removed memory", entry_id))
    return summaries


def _format_memory_change(prefix: str, entry_id) -> str:
    if isinstance(entry_id, int):
        return f"{prefix} id={entry_id}"
    return prefix
