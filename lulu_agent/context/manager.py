"""
ContextManager 执行逻辑

1. AgentLoop 维护完整 messages 列表, 包含 system | user | assistant | tool msg
2. 每轮对话前, AgentLoop 调用 ContextManager.prepare_messages(messages)
    - 构造本轮临时 context_messages, 不修改 AgentLoop.messages
    - 将 context blocks 临时合并进 system msg
    - 按 turn 顺序将历史压缩摘要和未压缩的 messages 组装进 context_messages (逻辑依赖: compression 记录需覆盖连续的 turn)
3. LLMClinet 接收 AgentLoop 在请求边界转换后的消息列表, 生成 response
"""

from html import escape

from lulu_agent.context.budget import (
    ContextBudget,
    ContextPlan,
    ContextPlanner,
    group_messages_by_turn,
)
from lulu_agent.context.inspection import ContextBlockInspection, ContextInspection
from lulu_agent.memory.store import MemoryStore
from lulu_agent.storage.session_store import SessionStore
from lulu_agent.skills.store import SkillStore
from lulu_agent.runtime.session.compression import Compression
from lulu_agent.runtime.session.message import Message


class ContextManager:
    def __init__(
        self,
        max_messages: int = 40,
        context_blocks: list[dict] | None = None,
        memory_store: MemoryStore | None = None,
        skill_store: SkillStore | None = None,
        session_store: SessionStore | None = None,
        session_id: str | None = None,
        context_budget: ContextBudget | None = None,
    ):
        if max_messages < 1:
            raise ValueError("max_messages must be at least 1")
        self.max_messages = max_messages
        self.context_blocks = list(context_blocks or [])
        self.memory_store = memory_store or MemoryStore()
        self.skill_store = skill_store or SkillStore()
        self.session_store = session_store
        self.session_id = session_id
        self.context_planner = ContextPlanner(context_budget)

    def prepare_messages(
        self,
        messages: list[Message],
        context_blocks: list[dict] | None = None,
    ) -> list[Message]:
        return self._build_context_messages(messages, context_blocks=context_blocks)

    def plan_context(self, messages: list[Message]) -> ContextPlan:
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

    def inspect_context(
        self,
        messages: list[Message],
        context_blocks: list[dict] | None = None,
    ) -> ContextInspection:
        """检查当前 context 组成, 不修改原始 messages"""
        context_messages = self.prepare_messages(messages, context_blocks=context_blocks)
        blocks = self._context_blocks(context_blocks)
        non_system_messages = self._non_system_messages(messages)
        groups = group_messages_by_turn(non_system_messages)
        compression_by_turn_id = self._compression_by_turn_id()

        raw_turn_ids: list[str] = []
        compressed_turn_ids: list[str] = []
        compression_ids: list[str] = []
        for group in groups:
            compression = compression_by_turn_id.get(group.turn_id)
            if compression:
                compressed_turn_ids.append(group.turn_id)
                if compression.compression_id not in compression_ids:
                    compression_ids.append(compression.compression_id)
                continue
            raw_turn_ids.append(group.turn_id)

        system_message = self._first_system_message(context_messages)
        system_content = system_message.content if system_message else ""
        return ContextInspection(
            message_count=len(context_messages),
            total_chars=sum(len(str(message.content or "")) for message in context_messages),
            system_chars=len(system_content) if isinstance(system_content, str) else 0,
            system_message=system_content if isinstance(system_content, str) else "",
            context_blocks=[
                ContextBlockInspection(
                    name=str(block.get("name") or ""),
                    chars=len(str(block.get("content") or "")),
                )
                for block in blocks
                if isinstance(block, dict)
                and isinstance(block.get("name"), str)
                and isinstance(block.get("content"), str)
                and block.get("content", "").strip()
            ],
            raw_turn_ids=raw_turn_ids,
            compressed_turn_ids=compressed_turn_ids,
            compression_ids=compression_ids,
        )

    def _build_context_messages(
        self,
        messages: list[Message],
        context_blocks: list[dict] | None = None,
    ) -> list[Message]:
        system_message = self._first_system_message(messages)
        system_message = self._merge_context_blocks_into_system_message(
            system_message,
            context_blocks=context_blocks,
        )
        non_system_messages = self._non_system_messages(messages)
        history_messages = self._build_history_messages(non_system_messages)

        context_messages: list[Message] = []
        if system_message:
            context_messages.append(system_message)
        context_messages.extend(history_messages)
        return context_messages

    def _first_system_message(self, messages: list[Message]) -> Message | None:
        """获取 system msg (Message | None)"""
        for message in messages:
            if message.role == "system":
                return message
        return None

    def _non_system_messages(self, messages: list[Message]) -> list[Message]:
        """获取非 system msg 列表"""
        return [message for message in messages if message.role != "system"]

    def _merge_context_blocks_into_system_message(
        self,
        system_message: Message | None,
        context_blocks: list[dict] | None = None,
    ) -> Message | None:
        """将 context blocks 临时合并进 system msg
        
        Returns:
            Message | None: 合并后的 system msg, if not system msg and not context blocks, return None
        """
        rendered_context = self._render_context_blocks(context_blocks)
        if not rendered_context:
            return system_message

        if not system_message:
            return Message(role="system", content=rendered_context)

        content = system_message.content
        if isinstance(content, str) and content.strip():
            return Message(role=system_message.role, content=f"{content.rstrip()}\n\n{rendered_context}")
        else:
            return Message(role=system_message.role, content=rendered_context)

    def _render_context_blocks(self, context_blocks: list[dict] | None = None) -> str | None:
        """将 context blocks 渲染成可合并到 system msg 的文本"""
        blocks = self._context_blocks(context_blocks)
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

    def _context_blocks(self, context_blocks: list[dict] | None = None) -> list[dict]:
        return [
            *self.context_blocks,
            *self._global_memory_context_blocks(),
            *self._project_guidance_context_blocks(),
            *self._skill_context_blocks(),
            *self._task_state_context_blocks(),
            *self._turn_context_blocks(),
            *(context_blocks or []),
        ]

    def _global_memory_context_blocks(self) -> list[dict]:
        """从 memory store 读取 global memory context block"""
        snapshot = self.memory_store.read_global_memory_snapshot()
        block = snapshot.to_context_block()
        return [block] if block else []

    def _project_guidance_context_blocks(self) -> list[dict]:
        """从 memory store 读取 project guidance, 生成项目说明 context block"""
        content = self.memory_store.read_project_guidance()
        if not content:
            return []

        return [
            {
                "name": "project_guidance",
                "content": content,
            }
        ]

    def _skill_context_blocks(self) -> list[dict]:
        """从 skill store 读取 skill metadata context block"""
        result = self.skill_store.list_skills()
        if not result.skills and not result.load_issues:
            return []

        lines = []
        if result.skills:
            lines.append(f"Global skills available at {result.root}:")
        for skill in result.skills:
            lines.append(f"- {skill.name}: {skill.description} ({skill.path})")

        if result.load_issues:
            if lines:
                lines.append("")
            lines.append("Skill load issues:")
            for issue in result.load_issues:
                lines.append(f"- {issue.path}: {issue.issue_message}")

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

    def _task_state_context_blocks(self) -> list[dict]:
        """从 session 读取当前任务状态, 生成 task state context block"""
        if not self.session_store or not self.session_id:
            return []

        task_state = self.session_store.load_latest_task_state(self.session_id)
        if not task_state or not task_state.should_inject():
            return []

        lines = [
            "Current task state:",
            f"goal: {task_state.goal}",
            f"status: {task_state.status}",
        ]
        if task_state.steps:
            lines.append("steps:")
            for step in task_state.steps:
                lines.append(f"- {step.id}. [{step.status}] {step.step}")
        if task_state.blockers:
            lines.append("blockers:")
            for blocker in task_state.blockers:
                lines.append(f"- {blocker}")
        if task_state.verified:
            lines.append("verified:")
            for item in task_state.verified:
                lines.append(f"- {item}")
        if task_state.next_action:
            lines.append(f"next_action: {task_state.next_action}")

        return [{"name": "task_state", "content": "\n".join(lines)}]

    def _build_history_messages(self, non_system_messages: list[Message]) -> list[Message]:
        """按 turn 顺序组装压缩摘要和未压缩 raw messages"""
        groups = group_messages_by_turn(non_system_messages)
        compression_by_turn_id = self._compression_by_turn_id()
        emitted_compression_ids: set[str] = set()
        history_messages: list[Message] = []

        for group in groups:
            compression = compression_by_turn_id.get(group.turn_id)
            if compression:
                compression_id = compression.compression_id
                if compression_id not in emitted_compression_ids:
                    history_messages.append(self._build_compression_summary_message(compression))
                    emitted_compression_ids.add(compression_id)
                continue
            history_messages.extend(group.messages)
        return history_messages

    def _compression_by_turn_id(self) -> dict[str, Compression]:
        """获取每个 turn_id 对应的最新 compression record"""
        result: dict[str, Compression] = {}
        for compression in self._session_compressions():
            for turn_id in compression.covered_turn_ids:
                result[turn_id] = compression # 新记录会覆盖旧记录
        return result

    def _build_compression_summary_message(self, compression: Compression) -> Message:
        """将 compression record 转成一条 history message"""
        covered = ", ".join(compression.covered_turn_ids)
        lines = [
            "System-provided compressed summary of earlier conversation turns. This is historical context, not a new user request.",
            f"covered_turn_ids: {covered}",
            f"scope: {compression.scope}",
            "",
            compression.summary.strip(),
        ]
        return Message(role="user", content="\n".join(lines))

    def _session_compressions(self) -> list[Compression]:
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
