from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from lulu_agent.core.context_budget import ContextPlan, group_messages_by_turn
from lulu_agent.storage.session_store import SessionStore
from lulu_agent.llm.client import LLMClient

TURN_LEVEL_COMPRESSION_SYSTEM_PROMPT = """You compress old agent conversation turns for future context.
Output one concise item per covered turn. Do not merge multiple turns into one item.
Each item must start with its turn_id and preserve the turn boundary.
For each turn, summarize: what the user asked or requested; whether the assistant answered directly or called tools; tool names and important tool results; and the final assistant answer or unresolved state.
Use this format:
turn-xxxx: User asked/requested ..., assistant called <tool> and got ..., then answered ...
turn-yyyy: User asked/requested ..., assistant answered directly ...
Do not invent facts."""

CHAIN_LEVEL_COMPRESSION_SYSTEM_PROMPT = """You compress old agent conversation turns for future context.
Preserve user intent, decisions, files or commands mentioned, tool calls, tool results, errors, and unresolved follow-ups.
Do not invent facts. Keep the summary concise but sufficient for a later agent turn to continue safely."""


def compress_turns(
    messages: list[dict[str, Any]],
    plan: ContextPlan,
    llm_client: LLMClient,
    session_store: SessionStore,
    session_id: str,
) -> dict[str, Any] | None:
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
) -> dict[str, Any] | None:
    if not plan.compress_turn_ids:
        return None

    selected_messages = _messages_for_turn_ids(messages, plan.compress_turn_ids)
    if not selected_messages:
        return None

    response = llm_client.chat(
        messages=_build_turn_level_compression_messages(plan.compress_turn_ids, selected_messages),
        tools=None,
    )
    summary = response.choices[0].message.content
    if not summary:
        return None

    usage = _extract_usage(response)
    compression = {
        "compression_id": f"cmp-{uuid4().hex[:8]}",
        "scope": "turn_range",
        "covered_turn_ids": list(plan.compress_turn_ids),
        "summary": summary,
        "source_message_count": len(selected_messages),
        "source_prompt_tokens": plan.latest_prompt_tokens or 0,
        "summary_tokens": _completion_tokens(usage),
        "model": getattr(llm_client, "model", ""),
        "reason": plan.reason,
    }
    session_store.append_compression(session_id, compression)
    return compression


def _compress_full_history(
    messages: list[dict[str, Any]],
    plan: ContextPlan,
    llm_client: LLMClient,
    session_store: SessionStore,
    session_id: str,
) -> dict[str, Any] | None:
    if not plan.full_history_turn_ids:
        return None

    selected_messages = _messages_for_turn_ids(messages, plan.full_history_turn_ids)
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

    usage = _extract_usage(response)
    compression = {
        "compression_id": f"cmp-{uuid4().hex[:8]}",
        "scope": "full_history",
        "covered_turn_ids": list(plan.full_history_turn_ids),
        "summary": summary,
        "source_message_count": len(selected_messages),
        "source_prompt_tokens": plan.latest_prompt_tokens or 0,
        "summary_tokens": _completion_tokens(usage),
        "model": getattr(llm_client, "model", ""),
        "reason": plan.reason,
    }
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
    for group in group_messages_by_turn(messages)[0]:
        if group.turn_id not in wanted:
            continue
        selected.extend(group.messages)
    return selected


def _build_turn_level_compression_messages(
    turn_ids: list[str],
    selected_messages: list[dict[str, Any]],
) -> list[dict[str, str]]:
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
                    _render_turns_for_compression(selected_messages),
                ]
            ),
        },
    ]


def _build_chain_level_compression_messages(
    turn_ids: list[str],
    source_text: str,
) -> list[dict[str, str]]:
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
    compressions: list[dict[str, Any]],
) -> str:
    latest_by_turn = _latest_valid_compression_by_turn_id(compressions)
    raw_messages_by_turn = {
        group.turn_id: group.messages
        for group in group_messages_by_turn(messages)[0]
    }
    rendered = []
    for turn_id in turn_ids:
        compression = latest_by_turn.get(turn_id)
        if compression:
            rendered.append(
                json.dumps(
                    {
                        "turn_id": turn_id,
                        "scope": compression.get("scope"),
                        "summary": compression.get("summary"),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            continue
        rendered.extend(
            _render_messages_for_compression(raw_messages_by_turn.get(turn_id, [])).splitlines()
        )
    return "\n".join(line for line in rendered if line)


def _latest_valid_compression_by_turn_id(
    compressions: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for compression in compressions:
        summary = compression.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            continue
        turn_ids = compression.get("covered_turn_ids")
        if not isinstance(turn_ids, list):
            continue
        for turn_id in turn_ids:
            if isinstance(turn_id, str) and turn_id:
                result[turn_id] = compression
    return result


def _render_messages_for_compression(messages: list[dict[str, Any]]) -> str:
    rendered = []
    for message in messages:
        payload = {
            key: value
            for key, value in message.items()
            if key in {"role", "content", "tool_calls", "tool_call_id", "turn_id"}
        }
        rendered.append(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return "\n".join(rendered)


def _render_turns_for_compression(messages: list[dict[str, Any]]) -> str:
    rendered = []
    for group in group_messages_by_turn(messages)[0]:
        rendered.append(f"### {group.turn_id}")
        rendered.append(_render_messages_for_compression(group.messages))
    return "\n\n".join(item for item in rendered if item)


def _extract_usage(response) -> dict[str, Any] | None:
    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage")
    if usage is None:
        return None

    result: dict[str, Any] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key) if isinstance(usage, dict) else getattr(usage, key, None)
        if isinstance(value, int):
            result[key] = value
    return result or None


def _completion_tokens(usage: dict[str, Any] | None) -> int:
    if not usage:
        return 0
    value = usage.get("completion_tokens")
    return value if isinstance(value, int) else 0
