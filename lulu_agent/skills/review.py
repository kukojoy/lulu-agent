from __future__ import annotations

from dataclasses import dataclass

from lulu_agent.context.manager import ContextManager
from lulu_agent.core.agent_loop import AgentLoop
from lulu_agent.llm.client import LLMClient
from lulu_agent.skills.store import SkillStore
from lulu_agent.storage.memory_store import MemoryStore
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


@dataclass(frozen=True)
class SkillReviewResult:
    response: str
    messages: list[dict]

    @property
    def updated(self) -> bool:
        for message in self.messages:
            if message.get("role") == "assistant" and message.get("tool_calls"):
                return True
        return False


class SkillReviewer:
    def __init__(
        self,
        llm_client: LLMClient | None = None,
        skill_store: SkillStore | None = None,
        max_turns: int = 20,
        review_turns: int = 8,
    ):
        self.llm_client = llm_client
        self.skill_store = skill_store or SkillStore()
        self.max_turns = max_turns
        self.review_turns = review_turns

    def review(self, messages_snapshot: list[dict]) -> SkillReviewResult:
        """后台检查对话是否需要更新 skill, 不污染主链路 messages/session"""
        sub_agent = AgentLoop(
            llm_client=self.llm_client,
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
            {"role": "system", "content": SKILL_REVIEW_PROMPT},
            *_recent_turn_messages(messages_snapshot, self.review_turns),
        ]
        response = sub_agent.run(
            "List current skills, then audit recent conversation for reusable skill improvements. "
            "Use skill_lookup and skill_manage to create candidates, refine existing skills, merge overlaps, or prune support files. "
            "Only answer Nothing to save after listing skills and deciding no operation is useful."
        )
        # print(f"[SkillReviewer] review result: {response}")  # DEBUG
        return SkillReviewResult(
            response=response,
            messages=list(sub_agent.messages),
        )


def _skill_only_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(skill_lookup)
    registry.register(skill_manage)
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
