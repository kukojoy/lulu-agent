def truncate_memory_text(text: str, max_chars: int) -> dict:
    """截断 memory context 文本, 返回截断元信息"""
    original_length = len(text)
    truncated = original_length > max_chars
    return {
        "text": text[:max_chars] if truncated else text,
        "truncated": truncated,
        "original_length": original_length,
    }
