"""
记忆存储模块, 用于记忆操作, 在会话中提供记忆上下文

当前特性:
1. 记忆存储在本地文件, 默认路径为工作目录下的 MEMORY.md, 每个记忆项用 "---" 分隔
2. 记忆存储层向工具层提供业务能力, 支持记忆的读, 增, 删, 改操作
3. 记忆存储层向上下文管理器提供记忆快照, 用于转换为 context block, 在每轮对话中提供记忆上下文
"""

from dataclasses import dataclass
from pathlib import Path

from lulu_agent.tools import truncate_text


DEFAULT_MEMORY_PATH = "MEMORY.md"
DEFAULT_MAX_MEMORY_CHARS = 4000
ENTRY_DELIMITER = "\n---\n"


@dataclass(frozen=True)
class MemorySnapshot:
    """记忆快照, 用于在会话中提供记忆上下文
    
    Attributes:
        path (str): 记忆文件的路径
        content (str): 记忆内容
        truncated (bool): 记忆内容截断标识
        original_length (int): 原始记忆内容长度
        entry_count (int): 记忆条目数量
    """
    path: str
    content: str
    truncated: bool
    original_length: int
    entry_count: int

    def to_context_block(self) -> dict | None:
        """将记忆快照转换为 context block"""
        if not self.content.strip():
            return None
        return {
            "name": "memory",
            "content": self.content,
        }


class MemoryStore:
    def __init__(
        self,
        path: str | Path = DEFAULT_MEMORY_PATH,
        max_chars: int = DEFAULT_MAX_MEMORY_CHARS,
    ):
        if max_chars < 1:
            raise ValueError("max_chars must be at least 1")
        self.path = Path(path)
        self.max_chars = max_chars

    def read_snapshot(self) -> MemorySnapshot:
        """从记忆文件中读取记忆快照"""
        entries = self._get_entries()
        content = self._serialize_entries(entries)
        truncated = truncate_text(content, self.max_chars) # NOTE: truncate_text 为工具层函数, 后期需要考虑解耦
        return MemorySnapshot(
            path=str(self.path.resolve()),
            content=truncated["text"],
            truncated=truncated["truncated"],
            original_length=truncated["original_length"],
            entry_count=len(entries),
        )

    def read(self) -> dict:
        """从记忆快照中解析记忆内容
        
        Returns:
            dict: 包含记忆内容和元信息
        """
        return self._result(True, "Memory read.")

    def add(self, content: str) -> dict:
        """向记忆中添加一条新内容"""
        content = content.strip()
        if not content:
            return self._result(False, "Memory content must not be empty.")

        entries = self._get_entries()
        if content in entries:
            return self._result(True, "Entry already exists.")

        entries.append(content)
        self._write_entries(entries)
        return self._result(True, "Entry added.")

    def replace(self, old_text: str, new_content: str) -> dict:
        """用新内容替换记忆中唯一匹配的旧内容"""
        old_text = old_text.strip()
        new_content = new_content.strip()
        if not old_text:
            return self._result(False, "old_text must not be empty.")
        if not new_content:
            return self._result(False, "new_content must not be empty.")

        entries = self._get_entries()
        match = self._unique_match(entries, old_text)
        if "error_msg" in match:
            return self._result(False, match["error_msg"], **match.get("extra", {}))

        entries[match["index"]] = new_content
        self._write_entries(entries)
        return self._result(True, "Entry replaced.")

    def remove(self, old_text: str) -> dict:
        """从记忆中删除唯一匹配的旧内容"""
        old_text = old_text.strip()
        if not old_text:
            return self._result(False, "old_text must not be empty.")

        entries = self._get_entries()
        match = self._unique_match(entries, old_text)
        if "error_msg" in match:
            return self._result(False, match["error_msg"], **match.get("extra", {}))

        entries.pop(match["index"])
        self._write_entries(entries)
        return self._result(True, "Entry removed.")

    def _write_entries(self, entries: list[str]) -> None:
        """将记忆条目列表写入文件"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(self._serialize_entries(entries), encoding="utf-8")

    def _get_entries(self) -> list[str]:
        """获取记忆条目列表 (用 ENTRY_DELIMITER 分隔)"""
        if not self.path.exists():
            return []
        raw = self.path.read_text(encoding="utf-8")
        if not raw.strip():
            return []
        return [entry.strip() for entry in raw.split(ENTRY_DELIMITER) if entry.strip()]

    def _serialize_entries(self, entries: list[str]) -> str:
        """将记忆条目列表转换为字符串, 用 ENTRY_DELIMITER 拼接"""
        return ENTRY_DELIMITER.join(entries)

    def _unique_match(self, entries: list[str], old_text: str) -> dict:
        """在记忆条目列表中查找唯一匹配项, 匹配规则: old_text 是条目内容的子串
        
        Returns:
            dict: 如果找到唯一匹配项, 返回 {"index": index}
        """
        matches = [(index, entry) for index, entry in enumerate(entries) if old_text in entry]
        if not matches:
            return {"error_msg": f"No memory entry matched '{old_text}'."}
        if len(matches) > 1:
            return {
                "error_msg": f"Multiple memory entries matched '{old_text}'. Be more specific.",
                "extra": {
                    "matches": [entry[:80] for _, entry in matches],
                },
            }
        return {"index": matches[0][0]}

    def _result(self, ok: bool, message: str, **kwargs) -> dict:
        """返回记忆快照操作状态
        
        Args:
            ok (bool): 操作是否成功
            message (str): 操作状态消息
            **kwargs: 其他附加信息
        """
        if not ok:
            return {
                "ok": ok,
                "error": message,
                **kwargs,
            }

        entries = self._get_entries()
        snapshot = self.read_snapshot()

        return {
            "ok": ok,
            "message": message,
            "path": snapshot.path,
            "content": snapshot.content,
            "entry_count": len(entries),
            "truncated": snapshot.truncated,
            "original_length": snapshot.original_length,
            **kwargs,
        }
