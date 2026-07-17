DEFAULT_MAX_TEXT_CHARS = 4000


def truncate_text(text: str, max_chars: int = DEFAULT_MAX_TEXT_CHARS) -> dict:
    """文本截断工具函数, 用于具体 Tool 对其 output 进行截断 (业务层)"""
    original_length = len(text)
    truncated = original_length > max_chars
    return {
        "text": text[:max_chars] if truncated else text,
        "truncated": truncated,
        "original_length": original_length,
    }


def truncate_middle_text(text: str, max_chars: int = DEFAULT_MAX_TEXT_CHARS) -> str:
    """文本截断工具函数, 用于 ToolRuntime 对 ToolResult 整体进行截断
    
    处理逻辑:
        1. if max_chars <= 0, 返回空字符串
        2. if original_length <= max_chars, 返回原始文本
        3. 截断文本中间部分, 前后长度按 max_chars 均分, 并在中间插入 marker
    """
    if max_chars <= 0:
        return ""
    
    original_length = len(text)
    if original_length <= max_chars:
        return text

    marker_template = "\n... [TRUNCATED - {omitted} chars omitted out of {total} total] ...\n"
    
    omitted = original_length - max_chars
    marker = marker_template.format(omitted=omitted, total=original_length)
 
    head_chars = max_chars // 2
    tail_chars = max_chars - head_chars
    return f"{text[:head_chars]}{marker}{text[-tail_chars:]}"
