from __future__ import annotations

import json

from lulu_agent.context.manager import ContextManager
from lulu_agent.core.agent_loop import AgentLoop
from lulu_agent.llm.client import LLMClient
from lulu_agent.runtime.session.message import Message
from lulu_agent.reviewers.base import BaseReviewer, BaseReviewResult, ReviewerType
from lulu_agent.skills.store import SkillStore
from lulu_agent.memory.store import MemoryStore
from lulu_agent.tools import ToolRegistry
from lulu_agent.tools.native.skill_lookup import skill_lookup
from lulu_agent.tools.native.skill_manage import skill_manage


SKILL_REVIEW_PROMPT = """Audit and maintain global reusable skills using the recent conversation and existing skills.

Use skills only for reusable procedures, workflows, tool usage patterns, or task methods.
Always call skill_lookup list first. Do not answer Nothing to save before inspecting current skill metadata.

Allowed maintenance patterns:
- create candidate: create a new skill when recent conversation reveals a reusable procedure not covered by existing skills.
- refine: improve an existing skill when recent conversation shows a clearer, more accurate, or more reliable workflow.
- merge: consolidate overlapping skill guidance by patching or updating the better target skill.
- prune: remove obsolete or low-value support files, or simplify bloated skill content.

Skill quality rules:
- Before modifying an existing skill, call skill_lookup read for that skill.
- Prefer skill_manage patch for targeted changes.
- Use skill_manage update only when patch cannot express the change cleanly or the whole SKILL.md must be restructured.
- Use skill_manage create with name and description first; then patch the generated template instead of passing full body content to create.
- Use write_file only for reusable references, templates, or scripts that keep SKILL.md concise.
- Do not create skills for one-off tasks, project-specific instructions, temporary failures, user facts, memory, secrets, or task state.

If no skill should be created, refined, merged, or pruned, answer exactly: Nothing to save."""


class SkillReviewResult(BaseReviewResult):
    pass


class SkillReviewer(BaseReviewer):
    def __init__(
        self,
        skill_store: SkillStore | None = None,
        max_turns: int = 20,
        review_turns: int = 8,
    ):
        self.type = ReviewerType.SKILLS
        self.skill_store = skill_store or SkillStore()
        self.max_turns = max_turns
        self.review_turns = review_turns

    def review(self, messages_snapshot: list[Message], llm_client: LLMClient) -> SkillReviewResult:
        """后台检查对话是否需要更新 skill, 不污染主链路 messages/session"""
        sub_agent = AgentLoop(
            llm_client=llm_client,
            tool_registry=_skill_only_registry(),
            context_manager=ContextManager(
                memory_store=MemoryStore(
                    ".lulu/memory_empty/MEMORY.md",
                    ".lulu/project_guidance_empty/AGENTS.md",
                ),
                skill_store=self.skill_store,
            ),
            max_turns=self.max_turns,
        )
        sub_agent.messages = [
            Message(role="system", content=SKILL_REVIEW_PROMPT),
            *_recent_turn_messages(messages_snapshot, self.review_turns),
        ]
        review_start = len(sub_agent.messages)
        response = sub_agent.run(
            "List current skills, then audit recent conversation for reusable skill improvements. "
            "Use skill_lookup and skill_manage to create candidates, refine existing skills, merge overlaps, or prune support files. "
            "Only answer Nothing to save after listing skills and deciding no operation is useful."
        )

        review_messages = sub_agent.messages[review_start:]
        tool_calls = _get_tool_calls(review_messages)
        tool_results = _get_tool_results(review_messages)
        summaries = _get_summaries(tool_calls, tool_results)

        return SkillReviewResult(
            response=response,
            summaries=summaries,
        )


def _skill_only_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(skill_lookup)
    registry.register(skill_manage)
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
    """从 tool_calls 中提取已完成的 skill 操作, 并生成摘要"""
    summaries = []
    for tool_call in tool_calls:
        tool_call_id = tool_call.get("id")
        if tool_call_id not in tool_results or tool_call.get("function", {}).get("name") != "skill_manage":
            continue

        arguments = tool_call.get("function", {}).get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                continue
        if not isinstance(arguments, dict):
            continue
        summary = _format_skill_change(arguments)
        if summary:
            summaries.append(summary)
    return summaries


def _format_skill_change(arguments: dict) -> str:
    action = arguments.get("action")
    name = arguments.get("name")
    if not isinstance(name, str) or not name:
        return ""
    if action == "create":
        return f"created skill {name}"
    if action == "update":
        return f"updated skill {name}"
    if action == "patch":
        return f"patched skill {name}"
    if action == "write_file":
        file_path = arguments.get("file_path")
        return _format_skill_file_change("updated skill support file", name, file_path)
    if action == "remove_file":
        file_path = arguments.get("file_path")
        return _format_skill_file_change("removed skill support file", name, file_path)
    return ""


def _format_skill_file_change(prefix: str, name: str, file_path) -> str:
    if isinstance(file_path, str) and file_path:
        return f"{prefix} {name}/{file_path}"
    return f"{prefix} {name}"
