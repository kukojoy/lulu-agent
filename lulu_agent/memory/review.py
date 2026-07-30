from __future__ import annotations

from dataclasses import dataclass, field

from lulu_agent.llm.client import LLMClient
from lulu_agent.context.manager import ContextManager
from lulu_agent.core.agent_loop import AgentLoop
from lulu_agent.memory.store import MemoryStore
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


@dataclass(frozen=True)
class MemoryReviewResult:
    response: str
    messages: list[dict]

    @property
    def updated(self) -> bool:
        for message in self.messages:
            if message.get("role") == "assistant" and message.get("tool_calls"):
                return True
        return False


class MemoryReviewer:
    def __init__(
        self,
        llm_client: LLMClient | None = None,
        memory_store: MemoryStore | None = None,
        max_turns: int = 20,
        review_turns: int = 8,
    ):
        self.llm_client = llm_client
        self.memory_store = memory_store or MemoryStore()
        self.max_turns = max_turns
        self.review_turns = review_turns

    def review(self, messages_snapshot: list[dict]) -> MemoryReviewResult:
        """后台检查对话是否需要更新 memory, 不污染主链路 messages/session"""
        sub_agent = AgentLoop(
            llm_client=self.llm_client,
            tool_registry=_memory_only_registry(),
            context_manager=ContextManager(
                memory_store=self.memory_store,
                skill_store=SkillStore(".lulu/skills_empty"),  # NOTE: 需保证路径 ".lulu/skills_empty" 不存在或为空目录
            ),
            max_turns=self.max_turns,
        )
        sub_agent.messages = [
            {"role": "system", "content": MEMORY_REVIEW_PROMPT},
            *_recent_turn_messages(messages_snapshot, self.review_turns),
        ]
        response = sub_agent.run(
            "Read current memory, then audit recent conversation and existing entries. "
            "Use memory add/update/remove to add candidates, merge overlaps, refine unclear entries, or prune low-value entries. "
            "Only answer Nothing to save after reading memory and deciding no operation is useful."
        )
        # print(f"[MemoryReviewer] review result: {response}")  # DEBUG
        return MemoryReviewResult(
            response=response,
            messages=list(sub_agent.messages),
        )


def _memory_only_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(memory)
    return registry


def _recent_turn_messages(messages: list[dict], recent_turns: int) -> list[dict]:
    turn_ids = []
    for message in messages:
        turn_id = message.get("turn_id")
        if turn_id and turn_id not in turn_ids:
            turn_ids.append(turn_id)

    selected_turn_ids = set(turn_ids[-recent_turns:])
    selected = []
    for message in messages:
        if message.get("role") == "system":
            continue
        if selected_turn_ids and message.get("turn_id") not in selected_turn_ids:
            continue
        selected.append(dict(message))
    return selected
