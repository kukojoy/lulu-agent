from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from lulu_agent.context.budget import ContextPlan, group_messages_by_turn
from lulu_agent.llm.client import LLMClient
from lulu_agent.llm.usage import extract_usage
from lulu_agent.runtime.compression import CompressionRecord, CompressionScope
from lulu_agent.storage.session_store import SessionStore

TURN_LEVEL_COMPRESSION_SYSTEM_PROMPT = """You compress old agent conversation turns for future context reconstruction.
The output should preserve about 20%-30% of the source information. Prefer a longer summary over losing details that may matter later.
Output one item per covered turn. Do not merge multiple turns into one item.
Each item must start with its turn_id and preserve the turn boundary, order, and causal flow.
For each turn, preserve: what the user asked or requested; important user constraints or preferences; whether the assistant answered directly or called tools; tool names, arguments, and important tool results; files, commands, identifiers, errors, and decisions mentioned; and the final assistant answer or unresolved state.
Use the same language as the source context. If the source is mostly Chinese, write the summary in Chinese; if it is mostly English, write in English.
Use this format:
turn-xxxx: User asked/requested ..., assistant called <tool> with ..., got ..., then answered ...
turn-yyyy: User asked/requested ..., assistant answered directly ...
Do not invent facts. Do not collapse concrete details into vague high-level conclusions."""

CHAIN_LEVEL_COMPRESSION_SYSTEM_PROMPT = """You compress old agent conversation context for future context reconstruction.
The output should preserve about 20%-30% of the source information. Prefer a longer summary over losing details that may matter later.
Preserve user intent, stable preferences, architecture decisions, files or commands mentioned, tool calls, tool results, errors, constraints, unresolved follow-ups, and current project state.
Organize the summary so a later agent turn can continue safely without the original context.
Use the same language as the source context. If the source is mostly Chinese, write the summary in Chinese; if it is mostly English, write in English.
Do not invent facts. Do not collapse concrete details into vague high-level conclusions."""


def compress_turns(
    messages: list[dict[str, Any]],
    plan: ContextPlan,
    llm_client: LLMClient,
    session_store: SessionStore,
    session_id: str,
) -> CompressionRecord | None:
    """根据 context plan 压缩历史 turn, 并存储压缩摘要
    
    Args:
        messages (list[dict]): 历史消息列表
        plan (ContextPlan): 上下文压缩计划
        llm_client (LLMClient): LLM 客户端
        session_store (SessionStore): 会话存储器
        session_id (str): 会话 ID
    """
    if plan.action != "compress_needed":
        return None

    compression = None
    if plan.compress_turn_ids:
        compression = _compress_old_turns(
            messages=messages,
            plan=plan,
            llm_client=llm_client,
            session_store=session_store,
            session_id=session_id,
        )

    if plan.full_history_turn_ids:
        full_history_compression = _compress_full_history(
            messages=messages,
            plan=plan,
            llm_client=llm_client,
            session_store=session_store,
            session_id=session_id,
        )
        if full_history_compression:
            compression = full_history_compression

    return compression


def _compress_old_turns(
    messages: list[dict[str, Any]],
    plan: ContextPlan,
    llm_client: LLMClient,
    session_store: SessionStore,
    session_id: str,
) -> CompressionRecord | None:
    if not plan.compress_turn_ids:
        return None

    selected_messages = _messages_for_turn_ids(messages, plan.compress_turn_ids)
    if not selected_messages:
        return None
    source_text = _render_turns_for_compression(selected_messages)
    if not source_text:
        return None

    response = llm_client.chat(
        messages=_build_turn_level_compression_messages(plan.compress_turn_ids, source_text),
        tools=None,
    )
    summary = response.choices[0].message.content
    if not summary:
        return None

    usage = extract_usage(response)
    compression = CompressionRecord(
        compression_id=f"cmp-{uuid4().hex[:8]}",
        scope=CompressionScope.TURN_RANGE,
        covered_turn_ids=list(plan.compress_turn_ids),
        summary=summary,
        source_prompt_chars=len(source_text),
        summary_chars=len(summary),
        summary_tokens=usage.get("completion_tokens") if usage else None,
        model=getattr(llm_client, "model", ""),
        reason=plan.reason,
    )
    session_store.append_compression(session_id, compression)
    return compression


def _compress_full_history(
    messages: list[dict[str, Any]],
    plan: ContextPlan,
    llm_client: LLMClient,
    session_store: SessionStore,
    session_id: str,
) -> CompressionRecord | None:
    if not plan.full_history_turn_ids:
        return None

    source_text = _render_full_history_source(
        messages=messages,
        turn_ids=plan.full_history_turn_ids,
        compressions=session_store.load_compressions(session_id),
    )
    if not source_text:
        return None

    response = llm_client.chat(
        messages=_build_chain_level_compression_messages(plan.full_history_turn_ids, source_text),
        tools=None,
    )
    summary = response.choices[0].message.content
    if not summary:
        return None

    usage = extract_usage(response)
    compression = CompressionRecord(
        compression_id=f"cmp-{uuid4().hex[:8]}",
        scope=CompressionScope.FULL_HISTORY,
        covered_turn_ids=list(plan.full_history_turn_ids),
        summary=summary,
        source_prompt_chars=len(source_text),
        summary_chars=len(summary),
        summary_tokens=usage.get("completion_tokens") if usage else None,
        model=getattr(llm_client, "model", ""),
        reason=plan.reason,
    )
    session_store.append_compression(session_id, compression)
    return compression


def _messages_for_turn_ids(
    messages: list[dict[str, Any]],
    turn_ids: list[str],
) -> list[dict[str, Any]]:
    """从消息列表中筛选出指定 turn_id 的消息
    
    Args:
        messages (list[dict]): 消息列表
        turn_ids (list[str]): 需要筛选的 turn_id 列表
    Returns:
        list[dict]: 筛选后的消息列表
    """
    wanted = set(turn_ids)
    selected: list[dict[str, Any]] = []
    for group in group_messages_by_turn(messages):
        if group.turn_id not in wanted:
            continue
        selected.extend(group.messages)
    return selected


def _build_turn_level_compression_messages(
    turn_ids: list[str],
    source_text: str,
) -> list[dict[str, str]]:
    """构造 turn-level 压缩 api messages"""
    return [
        {
            "role": "system",
            "content": TURN_LEVEL_COMPRESSION_SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": "\n".join(
                [
                    "Summarize these old conversation turns for future context.",
                    "Keep one item per covered turn, in the same order as the input.",
                    f"Covered turn ids: {', '.join(turn_ids)}",
                    "",
                    source_text,
                ]
            ),
        },
    ]


def _build_chain_level_compression_messages(
    turn_ids: list[str],
    source_text: str,
) -> list[dict[str, str]]:
    """构造 chain-level 压缩 api messages"""
    return [
        {
            "role": "system",
            "content": CHAIN_LEVEL_COMPRESSION_SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": "\n".join(
                [
                    "Summarize these existing context summaries into a smaller full-history summary.",
                    f"Covered turn ids: {', '.join(turn_ids)}",
                    "",
                    source_text,
                ]
            ),
        },
    ]


def _render_full_history_source(
    messages: list[dict[str, Any]],
    turn_ids: list[str],
    compressions: list[CompressionRecord],
) -> str:
    latest_by_turn = _latest_valid_compression_by_turn_id(compressions)
    raw_messages_by_turn = {
        group.turn_id: group.messages
        for group in group_messages_by_turn(messages)
    }
    rendered = []
    emitted_compression_ids: set[str] = set()
    for turn_id in turn_ids:
        compression = latest_by_turn.get(turn_id)
        if compression:
            if compression.compression_id not in emitted_compression_ids:
                rendered.append(
                    json.dumps(
                        {
                            "covered_turn_ids": compression.covered_turn_ids,
                            "scope": compression.scope,
                            "summary": compression.summary,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
                emitted_compression_ids.add(compression.compression_id)
            continue
        rendered.extend(
            _render_messages_for_compression(raw_messages_by_turn.get(turn_id, [])).splitlines()
        ) # NOTE: 当前链路逻辑下, 触发 chain-level 压缩时, 所有的可压缩 turn 均会有压缩记录, 所以正常情况下该代码不会被触发. 例外: turn-level 压缩失败, 但仍继续触发 chain-level 压缩
    return "\n".join(line for line in rendered if line)


def _latest_valid_compression_by_turn_id(
    compressions: list[CompressionRecord],
) -> dict[str, CompressionRecord]:
    """根据 compressions 列表, 返回每个 turn_id 对应的最新有效压缩记录"""
    result: dict[str, CompressionRecord] = {}
    for compression in compressions:
        for turn_id in compression.covered_turn_ids:
            result[turn_id] = compression
    return result


def _render_turns_for_compression(messages: list[dict[str, Any]]) -> str:
    """将 messages 按 turn 分组渲染为 JSON 字符串"""
    rendered = []
    for group in group_messages_by_turn(messages):
        rendered.append(f"### {group.turn_id}")
        rendered.append(_render_messages_for_compression(group.messages))
    return "\n\n".join(item for item in rendered if item)


def _render_messages_for_compression(messages: list[dict[str, Any]]) -> str:
    """将某个 turn 分组的 messages 渲染为 JSON 字符串"""
    rendered = []
    for message in messages:
        payload = {
            key: value
            for key, value in message.items()
            if key in {"role", "content", "tool_calls", "tool_call_id", "turn_id"}
        }
        rendered.append(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return "\n".join(rendered)
