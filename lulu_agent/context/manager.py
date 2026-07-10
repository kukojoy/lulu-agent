"""
ContextManager 执行逻辑

1. AgentLoop 维护完整 messages 列表, 包含 system | user | assistant | tool msg
2. 每轮对话前, AgentLoop 调用 ContextManager.prepare_messages(messages)
    - 构造本轮临时 api_messages, 不修改 AgentLoop.messages
    - 将 context blocks 临时合并进 system msg
    - 按 turn 顺序将历史压缩摘要和未压缩 raw turn messages 组装进 api_messages
3. LLMClinet 接收 ContextManager 返回的消息列表, 生成 response
"""

from html import escape

from lulu_agent.context.budget import (
    ContextBudget,
    ContextPlan,
    ContextPlanner,
    group_messages_by_turn,
)
from lulu_agent.storage.memory_store import MemoryStore
from lulu_agent.storage.session_store import SessionStore
from lulu_agent.skills.loader import SkillLoader
from lulu_agent.runtime.compression import CompressionRecord


class ContextManager:
    def __init__(
        self,
        max_messages: int = 40,
        context_blocks: list[dict] | None = None,
        memory_store: MemoryStore | None = None,
        skill_loader: SkillLoader | None = None,
        session_store: SessionStore | None = None,
        session_id: str | None = None,
        context_budget: ContextBudget | None = None,
    ):
        if max_messages < 1:
            raise ValueError("max_messages must be at least 1")
        self.max_messages = max_messages
        self.context_blocks = list(context_blocks or [])
        self.memory_store = memory_store or MemoryStore()
        self.skill_loader = skill_loader or SkillLoader()
        self.session_store = session_store
        self.session_id = session_id
        self.context_planner = ContextPlanner(context_budget)

    def prepare_messages(
        self,
        messages: list[dict],
        context_blocks: list[dict] | None = None,
    ) -> list[dict]:
        return self._build_api_messages(messages, context_blocks=context_blocks)

    def plan_context(self, messages: list[dict]) -> ContextPlan:
        turns = []
        compressions = []
        if self.session_store and self.session_id:
            turns = self.session_store.load_turns(self.session_id)
            compressions = self.session_store.load_compressions(self.session_id)
        return self.context_planner.plan(
            messages=messages,
            turns=turns,
            compressions=compressions,
        )

    def _build_api_messages(
        self,
        messages: list[dict],
        context_blocks: list[dict] | None = None,
    ) -> list[dict]:
        system_message = self._first_system_message(messages)
        system_message = self._merge_context_blocks_into_system_message(
            system_message,
            context_blocks=context_blocks,
        )
        non_system_messages = self._non_system_messages(messages)
        context_messages = self._build_turn_context_messages(non_system_messages)

        api_messages = []
        if system_message:
            api_messages.append(system_message)
        api_messages.extend(context_messages) # NOTE: 这些 messages 可能包含 turn_id 字段, 但不影响 LLM 请求
        return api_messages

    def _first_system_message(self, messages: list[dict]) -> dict | None:
        """获取 system msg (dict | None)"""
        for message in messages:
            if message.get("role") == "system":
                return message
        return None

    def _non_system_messages(self, messages: list[dict]) -> list[dict]:
        """获取非 system msg 列表"""
        return [message for message in messages if message.get("role") != "system"]

    def _merge_context_blocks_into_system_message(
        self,
        system_message: dict | None,
        context_blocks: list[dict] | None = None,
    ) -> dict | None:
        """将 context blocks 临时合并进 system msg
        
        Returns:
            dict | None: 合并后的 system msg, if not system msg and not context blocks, return None
        """
        rendered_context = self._render_context_blocks(context_blocks)
        if not rendered_context:
            return system_message

        if not system_message:
            return {"role": "system", "content": rendered_context}

        merged = dict(system_message) # 浅拷贝, 避免修改原 system_message
        content = merged.get("content")
        if isinstance(content, str) and content.strip():
            merged["content"] = f"{content.rstrip()}\n\n{rendered_context}"
        else:
            merged["content"] = rendered_context
        return merged

    def _render_context_blocks(self, context_blocks: list[dict] | None = None) -> str | None:
        """将 context blocks 渲染成可合并到 system msg 的文本"""
        blocks = [
            *self.context_blocks,
            *self._memory_context_blocks(),
            *self._skill_context_blocks(),
            *self._turn_context_blocks(),
            *(context_blocks or []),
        ]
        rendered_blocks = []
        for block in blocks:
            rendered = self._render_context_block(block)
            if rendered:
                rendered_blocks.append(rendered)

        if not rendered_blocks:
            return None

        return "\n".join(
            [
                "<context_blocks>",
                *rendered_blocks,
                "</context_blocks>",
            ]
        )

    def _memory_context_blocks(self) -> list[dict]:
        """从 memory store 读取 memory context block"""
        snapshot = self.memory_store.read_snapshot()
        block = snapshot.to_context_block()
        return [block] if block else []

    def _skill_context_blocks(self) -> list[dict]:
        """从 skill loader 读取 skill metadata context block"""
        result = self.skill_loader.list_skills()
        if not result.skills and not result.errors:
            return []

        lines = []
        if result.skills:
            lines.append("Local workspace skills available in .lulu/skills:")
        for skill in result.skills:
            lines.append(f"- {skill.name}: {skill.description} ({skill.path})")

        if result.errors:
            if lines:
                lines.append("")
            lines.append("Skill load errors:")
            for error in result.errors:
                lines.append(f"- {error.path}: {error.error}")

        return [
            {
                "name": "skills",
                "content": "\n".join(lines),
            }
        ]

    def _turn_context_blocks(self) -> list[dict]:
        """从 session turns 读取上一轮异常结束状态, 生成 runtime context block"""
        if not self.session_store or not self.session_id:
            return []

        turns = self.session_store.load_turns(self.session_id)
        if not turns:
            return []

        latest = turns[-1]
        status = latest.status
        if status not in {"interrupted", "failed"}:
            return []

        exit_reason = latest.exit_reason or "unknown_error"
        error = latest.error or ""
        content = "\n".join(
            [
                "The previous agent turn ended abnormally.",
                f"status: {status}",
                f"exit_reason: {exit_reason}",
                f"model_calls: {latest.model_calls}",
                f"tool_calls: {latest.tool_calls}",
                f"error: {error}" if error else "error: none",
                "",
                "Do not assume the previous turn completed successfully. If the previous turn may have changed files, run commands, or used tools, inspect the relevant state before continuing.",
            ]
        )
        return [
            {
                "name": "previous_turn_status",
                "content": content,
            }
        ]

    def _build_turn_context_messages(self, non_system_messages: list[dict]) -> list[dict]:
        """按 turn 顺序组装压缩摘要和未压缩 raw messages"""
        groups = group_messages_by_turn(non_system_messages)
        compression_by_turn_id = self._compression_by_turn_id()
        emitted_compression_ids: set[str] = set()
        context_messages = []

        for group in groups:
            compression = compression_by_turn_id.get(group.turn_id)
            if compression:
                compression_id = compression.compression_id
                if compression_id not in emitted_compression_ids:
                    context_messages.append(self._compression_message(compression))
                    emitted_compression_ids.add(compression_id)
                continue
            context_messages.extend(group.messages)
        return context_messages

    def _compression_by_turn_id(self) -> dict[str, CompressionRecord]:
        """获取每个 turn_id 对应的最新 compression record"""
        result: dict[str, CompressionRecord] = {}
        for compression in self._session_compressions():
            for turn_id in compression.covered_turn_ids:
                result[turn_id] = compression # 新记录会覆盖旧记录
        return result

    def _compression_message(self, compression: CompressionRecord) -> dict:
        """将 compression record 转成临时 api context message"""
        covered = ", ".join(compression.covered_turn_ids)
        lines = [
            "Compressed summary of earlier conversation turns.",
            f"covered_turn_ids: {covered}",
            f"scope: {compression.scope}",
            "",
            compression.summary.strip(),
        ]
        return {
            "role": "user",
            "content": "\n".join(lines),
        }

    def _session_compressions(self) -> list[CompressionRecord]:
        if not self.session_store or not self.session_id:
            return []
        return self.session_store.load_compressions(self.session_id)

    def _render_context_block(self, block: dict) -> str | None:
        """渲染单个 context block
        
        Args:
            block (dict): context block, 包含 name 和 content 字段
        
        Returns:
            str | None: 渲染后的字符串, 如果 block 无效则返回 None
        """

        if not isinstance(block, dict):
            return None
        name = block.get("name")
        content = block.get("content")
        if not isinstance(name, str) or not name.strip():
            return None
        if not isinstance(content, str) or not content.strip():
            return None

        escaped_name = escape(name.strip(), quote=True) # 转义 name 中的特殊字符, 防止破坏标签结构
        return "\n".join(
            [
                f'<context_block name="{escaped_name}">',
                content.strip(),
                "</context_block>",
            ]
        )
