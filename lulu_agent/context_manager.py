"""
ContextManager 执行逻辑

1. AgentLoop 维护完整 messages 列表, 包含 system | user | assistant | tool msg
2. 每轮对话前, AgentLoop 调用 ContextManager.prepare_messages(messages)
    - 筛出 system msg 和 最近的 max_messages 条非 system msg
    - 如果裁剪后的第一条消息来自 tool, 额外包含其 tool-call assistant msg
    - 返回 system + [selected non-system messages] 
3. LLMClinet 接收 ContextManager 返回的消息列表, 生成 response
"""

class ContextManager:
    def __init__(self, max_messages: int = 40):
        if max_messages < 1:
            raise ValueError("max_messages must be at least 1")
        self.max_messages = max_messages

    def prepare_messages(self, messages: list[dict]) -> list[dict]:
        system_message = self._first_system_message(messages)
        non_system_messages = [
            message for message in messages if message.get("role") != "system"
        ]

        if len(non_system_messages) <= self.max_messages:
            return list(messages)

        start = len(non_system_messages) - self.max_messages
        selected = non_system_messages[start:]
        selected = self._include_tool_call_parent(non_system_messages, start, selected)

        if system_message:
            return [system_message, *selected]
        return selected

    def _first_system_message(self, messages: list[dict]) -> dict | None:
        for message in messages:
            if message.get("role") == "system":
                return message
        return None

    def _include_tool_call_parent(
        self,
        non_system_messages: list[dict],
        start: int,
        selected: list[dict],
    ) -> list[dict]:
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
        if not tool_call_id:
            return None

        for message in reversed(candidates):
            if message.get("role") != "assistant":
                continue
            for tool_call in message.get("tool_calls", []):
                if tool_call.get("id") == tool_call_id:
                    return message
        return None
