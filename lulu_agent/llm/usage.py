from __future__ import annotations

from typing import Any


USAGE_TOKEN_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens")


def extract_usage(response: Any) -> dict[str, Any] | None:
    """提取 LLM 响应中的 usage 信息
    
    Args:
        response: LLM 响应
    
    Returns:
        dict[str, Any] | None: usage 字典
    """
    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage")
    if usage is None:
        return None

    result: dict[str, Any] = {}
    for key in USAGE_TOKEN_KEYS:
        token_amount = usage.get(key) if isinstance(usage, dict) else getattr(usage, key, None)
        if isinstance(token_amount, int):
            result[key] = token_amount
    return result or None
