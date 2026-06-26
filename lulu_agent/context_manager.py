"""
ContextManager 执行逻辑

1. AgentLoop 维护完整 messages 列表, 包含 system | user | assistant | tool msg
2. 每轮对话前, AgentLoop 调用 ContextManager.prepare_messages(messages)
    - 构造本轮临时 api_messages, 不修改 AgentLoop.messages
    - 将 context blocks 临时合并进 system msg
    - 筛出 system msg 和 最近的 max_messages 条非 system msg
    - 如果裁剪后的第一条消息来自 tool, 额外包含其 tool-call assistant msg
    - 返回合并后的 system + [selected non-system messages]
3. LLMClinet 接收 ContextManager 返回的消息列表, 生成 response
"""

from html import escape

from lulu_agent.memory_store import MemoryStore
from lulu_agent.skill_loader import SkillLoader


class ContextManager:
    def __init__(
        self,
        max_messages: int = 40,
        context_blocks: list[dict] | None = None,
        memory_store: MemoryStore | None = None,
        skill_loader: SkillLoader | None = None,
    ):
        if max_messages < 1:
            raise ValueError("max_messages must be at least 1")
        self.max_messages = max_messages
        self.context_blocks = list(context_blocks or [])
        self.memory_store = memory_store or MemoryStore()
        self.skill_loader = skill_loader or SkillLoader()

    def prepare_messages(
        self,
        messages: list[dict],
        context_blocks: list[dict] | None = None,
    ) -> list[dict]:
        return self._build_api_messages(messages, context_blocks=context_blocks)

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
        selected = self._recent_messages(non_system_messages)

        api_messages = []
        if system_message:
            api_messages.append(system_message)
        api_messages.extend(selected)
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

    def _recent_messages(self, non_system_messages: list[dict]) -> list[dict]:
        """获取最近的 max_messages 条非 system msg, 并包含 tool-call parent msg"""
        if len(non_system_messages) <= self.max_messages:
            return list(non_system_messages)

        start = len(non_system_messages) - self.max_messages
        selected = non_system_messages[start:]
        return self._include_tool_call_parent(non_system_messages, start, selected)

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

    def _include_tool_call_parent(
        self,
        non_system_messages: list[dict],
        start: int,
        selected: list[dict],
    ) -> list[dict]:
        """如果 selected 的第一条消息来自 tool, 则包含其 tool-call parent msg"""
        if not selected or selected[0].get("role") != "tool":
            return selected

        tool_call_id = selected[0].get("tool_call_id")
        parent = self._find_parent_tool_call(non_system_messages[:start], tool_call_id)
        if not parent:
            return selected
        return [parent, *selected]

    def _find_parent_tool_call(
        self,
        candidates: list[dict],
        tool_call_id: str | None,
    ) -> dict | None:
        """从 candidates 中找到 tool_call_id 对应的 parent msg"""
        if not tool_call_id:
            return None

        for message in reversed(candidates):
            if message.get("role") != "assistant":
                continue
            for tool_call in message.get("tool_calls", []):
                if tool_call.get("id") == tool_call_id:
                    return message
        return None
