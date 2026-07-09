from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


ContextCompressionAction = Literal[
    "no_compression_needed",
    "compress_needed",
]


@dataclass(frozen=True)
class ContextBudget:
    context_limit_tokens: int = 128000 # 最大限制 token 量
    compression_threshold_ratio: float = 0.8 # 压缩阈值比例
    recent_turns_to_keep: int = 3 # 保留最近的 turn
    full_history_trigger_turns: int = 3 # 连续超阈值 turn 数量达到该值时触发全量压缩

    def __post_init__(self) -> None:
        if self.context_limit_tokens < 1:
            raise ValueError("context_limit_tokens must be at least 1")
        if not 0 < self.compression_threshold_ratio <= 1:
            raise ValueError("compression_threshold_ratio must be greater than 0 and at most 1")
        if self.recent_turns_to_keep < 0:
            raise ValueError("recent_turns_to_keep must be at least 0")
        if self.full_history_trigger_turns < 1:
            raise ValueError("full_history_trigger_turns must be at least 1")

    @property
    def compression_threshold_tokens(self) -> int:
        return int(self.context_limit_tokens * self.compression_threshold_ratio) # 压缩阈值 = 最大限制 * 压缩比例


@dataclass(frozen=True)
class TurnMessageGroup:
    turn_id: str
    messages: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ContextPlan:
    """上下文压缩 Plan 对象
    
    Attributes:
        action (ContextCompressionAction): context 压缩决策
        reason (str): context 压缩决策原因
        latest_prompt_tokens (int | None): 最新一次 LLM 请求的 prompt_tokens
        threshold_tokens (int): context 压缩阈值 token 量
        context_limit_tokens (int): context 最大限制 token 量
        keep_turn_ids (list[str]): 要保留的最近 turn_id 列表
        compress_turn_ids (list[str]): 候选待压缩 turn_id 列表
        compressed_turn_ids (list[str]): 已经被压缩过的 turn_id 列表
        full_history_turn_ids (list[str]): 候选全量压缩 turn_id 列表
        unassigned_message_count (int): 未分组的消息数量
    """
    action: ContextCompressionAction
    reason: str
    latest_prompt_tokens: int | None
    threshold_tokens: int
    context_limit_tokens: int
    keep_turn_ids: list[str]
    compress_turn_ids: list[str]
    compressed_turn_ids: list[str]
    full_history_turn_ids: list[str]
    unassigned_message_count: int


class ContextPlanner:
    def __init__(self, budget: ContextBudget | None = None):
        self.budget = budget or ContextBudget()

    def plan(
        self,
        messages: list[dict[str, Any]],
        turns: list[dict[str, Any]] | None = None,
        compressions: list[dict[str, Any]] | None = None,
    ) -> ContextPlan:
        groups, unassigned_message_count = group_messages_by_turn(messages)
        turn_ids = [group.turn_id for group in groups]
        latest_prompt_tokens = latest_prompt_tokens_from_turns(turns or [])
        threshold_tokens = self.budget.compression_threshold_tokens
        consecutive_exceeded_turns = consecutive_prompt_exceeded_turn_count(
            turns or [],
            threshold_tokens,
        )
        should_compress_full_history = (
            consecutive_exceeded_turns >= self.budget.full_history_trigger_turns
        )
        keep_turn_ids = turn_ids[-self.budget.recent_turns_to_keep:] if self.budget.recent_turns_to_keep else []
        older_turn_ids = turn_ids[: len(turn_ids) - len(keep_turn_ids)]
        compressed_turn_ids = [
            turn_id for turn_id in older_turn_ids if turn_id in covered_turn_ids(compressions or [])
        ] # 历史中已经被压缩过的 turn_id
        compress_turn_ids = [
            turn_id for turn_id in older_turn_ids if turn_id not in compressed_turn_ids
        ] # 历史中还没有被压缩过的 turn_id

        # usage 缺失, 兜底不压缩
        if latest_prompt_tokens is None:
            return self._plan(
                action="no_compression_needed",
                reason="missing_usage",
                latest_prompt_tokens=latest_prompt_tokens,
                keep_turn_ids=keep_turn_ids,
                compress_turn_ids=[],
                compressed_turn_ids=compressed_turn_ids,
                full_history_turn_ids=[],
                unassigned_message_count=unassigned_message_count,
            )

        # usage < threshold, 不压缩
        if latest_prompt_tokens < threshold_tokens:
            return self._plan(
                action="no_compression_needed",
                reason="under_threshold",
                latest_prompt_tokens=latest_prompt_tokens,
                keep_turn_ids=keep_turn_ids,
                compress_turn_ids=[],
                compressed_turn_ids=compressed_turn_ids,
                full_history_turn_ids=[],
                unassigned_message_count=unassigned_message_count,
            )

        # usage >= threshold, 且存在候选待压缩 turn
        if compress_turn_ids:
            return self._plan(
                action="compress_needed",
                reason="threshold_exceeded_consecutive" if should_compress_full_history else "threshold_exceeded",
                latest_prompt_tokens=latest_prompt_tokens,
                keep_turn_ids=keep_turn_ids,
                compress_turn_ids=compress_turn_ids,
                compressed_turn_ids=compressed_turn_ids,
                full_history_turn_ids=older_turn_ids if should_compress_full_history else [],
                unassigned_message_count=unassigned_message_count,
            )

        return self._plan(
            action="no_compression_needed",
            reason="no_old_turns",
            latest_prompt_tokens=latest_prompt_tokens,
            keep_turn_ids=keep_turn_ids,
            compress_turn_ids=[],
            compressed_turn_ids=compressed_turn_ids,
            full_history_turn_ids=[],
            unassigned_message_count=unassigned_message_count,
        )

    def _plan(
        self,
        action: ContextCompressionAction,
        reason: str,
        latest_prompt_tokens: int | None,
        keep_turn_ids: list[str],
        compress_turn_ids: list[str],
        compressed_turn_ids: list[str],
        full_history_turn_ids: list[str],
        unassigned_message_count: int,
    ) -> ContextPlan:
        """封装 ContextPlan 对象"""
        return ContextPlan(
            action=action,
            reason=reason,
            latest_prompt_tokens=latest_prompt_tokens,
            threshold_tokens=self.budget.compression_threshold_tokens,
            context_limit_tokens=self.budget.context_limit_tokens,
            keep_turn_ids=keep_turn_ids,
            compress_turn_ids=compress_turn_ids,
            compressed_turn_ids=compressed_turn_ids,
            full_history_turn_ids=full_history_turn_ids,
            unassigned_message_count=unassigned_message_count,
        )


def group_messages_by_turn(messages: list[dict[str, Any]]) -> tuple[list[TurnMessageGroup], int]:
    """按 turn_id 将消息分组
    
    Args:
        messages: 消息列表
    
    Returns:
        tuple[list[TurnMessageGroup], int]: 消息组和未分配的消息数量
    """
    groups_by_id: dict[str, TurnMessageGroup] = {}
    groups: list[TurnMessageGroup] = []
    unassigned_message_count = 0

    for message in messages:
        if message.get("role") == "system":
            continue
        turn_id = message.get("turn_id")
        if not isinstance(turn_id, str) or not turn_id:
            unassigned_message_count += 1
            continue
        group = groups_by_id.get(turn_id)
        if group is None:
            group = TurnMessageGroup(turn_id=turn_id)
            groups_by_id[turn_id] = group
            groups.append(group)
        group.messages.append(message)

    return groups, unassigned_message_count


def latest_prompt_tokens_from_turns(turns: list[dict[str, Any]]) -> int | None:
    """从最近的 turn 中获取最近一次 LLM 请求的 prompt_tokens
    
    Args:
        turns (list[dict[str, Any]]): turns 列表, 每个 turn 是一个字典, 包含 model_usage 键
    Returns:
        int | None: 最新的 prompt_tokens 值
    """
    for turn in reversed(turns):
        model_usage = turn.get("model_usage")
        if not isinstance(model_usage, list):
            continue
        for usage in reversed(model_usage):
            if not isinstance(usage, dict):
                continue
            prompt_tokens = usage.get("prompt_tokens")
            if isinstance(prompt_tokens, int):
                return prompt_tokens
    return None


def consecutive_prompt_exceeded_turn_count(
    turns: list[dict[str, Any]],
    threshold_tokens: int,
) -> int:
    """从最新 turn 开始统计连续 prompt_tokens 超过阈值的 turn 数量"""
    count = 0
    for turn in reversed(turns):
        prompt_tokens = latest_prompt_tokens_from_turn(turn)
        if prompt_tokens is None or prompt_tokens < threshold_tokens:
            break
        count += 1
    return count


def latest_prompt_tokens_from_turn(turn: dict[str, Any]) -> int | None:
    """从某个 turn 中获取最新一次 LLM 请求的 prompt_tokens"""
    model_usage = turn.get("model_usage")
    if not isinstance(model_usage, list):
        return None
    for usage in reversed(model_usage):
        if not isinstance(usage, dict):
            continue
        prompt_tokens = usage.get("prompt_tokens")
        if isinstance(prompt_tokens, int):
            return prompt_tokens
    return None


def covered_turn_ids(compressions: list[dict[str, Any]]) -> set[str]:
    """获取已经被压缩过的 turn_id 集合"""
    covered: set[str] = set()
    for compression in compressions:
        turn_ids = compression.get("covered_turn_ids")
        if not isinstance(turn_ids, list):
            continue
        for turn_id in turn_ids:
            if isinstance(turn_id, str) and turn_id:
                covered.add(turn_id)
    return covered
