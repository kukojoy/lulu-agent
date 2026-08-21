"""
记忆存储模块, 用于记忆操作, 在会话中提供记忆上下文

当前特性:
1. 记忆存储在本地文件, 默认路径为 ~/.lulu/memory/MEMORY.md, 每个记忆项用 HTML comment JSON marker 标记
2. 记忆存储层向工具层提供业务能力, 支持记忆的读, 增, 删, 改操作
3. 记忆存储层向上下文管理器提供记忆快照, 用于转换为 context block, 在每轮对话中提供记忆上下文
"""

import json

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from lulu_agent.memory.utils import truncate_memory_text
from lulu_agent.runtime.errors import ERROR_INVALID_ARGUMENTS, ERROR_NOT_FOUND, ErrorType, LuluError
from lulu_agent.runtime.utils import exclusive_file_lock, get_local_time


DEFAULT_GLOBAL_MEMORY_PATH = Path.home() / ".lulu" / "memory" / "MEMORY.md"
DEFAULT_PROJECT_GUIDANCE_PATH = Path.cwd() / "AGENTS.md"
DEFAULT_MAX_MEMORY_CHARS = 4000
ENTRY_MARKER_PREFIX = "<!-- memory-entry "
ENTRY_MARKER_SUFFIX = " -->"
VALID_MEMORY_KINDS = {"preference", "fact"}


@dataclass(frozen=True)
class MemoryEntry:
    """结构化记忆条目"""

    id: int
    kind: str
    content: str
    updated_at: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "content": self.content,
            "updated_at": self.updated_at,
        }


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


@dataclass(frozen=True)
class MemoryResult:
    message: str = ""
    path: str = ""
    content: str = ""
    entries: list[MemoryEntry] = field(default_factory=list)
    truncated: bool = False
    original_length: int = 0
    entry: dict = field(default_factory=dict)

    def to_dict(self, fields: tuple[str, ...]) -> dict:
        data = {
            "entries": [entry.to_dict() for entry in self.entries],
            "entry": self.entry,
        }
        data.update(
            {
                "message": self.message,
                "path": self.path,
                "content": self.content,
                "truncated": self.truncated,
                "original_length": self.original_length,
            }
        )
        return {field: data[field] for field in fields}


class MemoryStoreError(LuluError):
    def __init__(self, error_message: str, error_type: ErrorType = ERROR_INVALID_ARGUMENTS):
        super().__init__(error_message, error_type)


class MemoryStore:
    def __init__(
        self,
        global_path: str | Path = DEFAULT_GLOBAL_MEMORY_PATH,
        project_path: str | Path = DEFAULT_PROJECT_GUIDANCE_PATH,
        max_chars: int = DEFAULT_MAX_MEMORY_CHARS,
    ):
        if max_chars < 1:
            raise ValueError("max_chars must be at least 1")
        self.global_path = Path(global_path)
        self.project_path = Path(project_path)
        self.max_chars = max_chars

    # === 对外接口 ===
    def read_project_guidance(self) -> str:
        """读取项目说明"""
        if not self.project_path.exists():
            return ""
        return self.project_path.read_text(encoding="utf-8").strip()

    def read_global_memory_snapshot(self) -> MemorySnapshot:
        """从记忆文件中读取记忆快照"""
        entries = self._get_entries()
        content = self._render_entries(entries)
        truncated = truncate_memory_text(content, self.max_chars)
        return MemorySnapshot(
            path=str(self.global_path.resolve()),
            content=truncated["text"],
            truncated=truncated["truncated"],
            original_length=truncated["original_length"],
            entry_count=len(entries),
        )

    def read(self) -> MemoryResult:
        """从记忆快照中解析记忆内容
        
        Returns:
            dict: 包含记忆内容和元信息
        """
        return self._result("Memory read.")

    def add(self, kind: str, content: str) -> MemoryResult:
        """向记忆中添加一条新内容"""
        self._validate_kind(kind)
        content = content.strip()
        self._validate_content(content)

        with self._file_lock():
            entries = self._get_entries()
            entry = MemoryEntry(
                id=self._next_id(entries),
                kind=kind,
                content=content,
                updated_at=get_local_time().isoformat(),
            )
            entries.append(entry)
            self._write_entries(entries)
            return self._result("Entry added.", entry=entry.to_dict())

    def update(self, entry_id: int, kind: str, content: str) -> MemoryResult:
        """按 id 更新记忆条目"""
        self._validate_id(entry_id)
        self._validate_kind(kind)
        content = content.strip()
        self._validate_content(content)

        with self._file_lock():
            entries = self._get_entries()
            index = self._find_index_by_id(entries, entry_id)
            if index is None:
                raise MemoryStoreError(f"No memory entry found with id {entry_id}.", ERROR_NOT_FOUND)

            entry = MemoryEntry(
                id=entry_id,
                kind=kind,
                content=content,
                updated_at=get_local_time().isoformat(),
            )
            entries[index] = entry
            self._write_entries(entries)
            return self._result("Entry updated.", entry=entry.to_dict())

    def remove(self, entry_id: int) -> MemoryResult:
        """按 id 删除记忆条目"""
        self._validate_id(entry_id)

        with self._file_lock():
            entries = self._get_entries()
            index = self._find_index_by_id(entries, entry_id)
            if index is None:
                raise MemoryStoreError(f"No memory entry found with id {entry_id}.", ERROR_NOT_FOUND)

            removed = entries.pop(index)
            self._write_entries(entries)
            return self._result("Entry removed.", entry=removed.to_dict())

    # === entry ===
    def _get_entries(self) -> list[MemoryEntry]:
        """从记忆文件中获取记忆条目列表"""
        if not self.global_path.exists():
            return []
        
        raw = self.global_path.read_text(encoding="utf-8")
        if not raw.strip():
            return []

        if ENTRY_MARKER_PREFIX in raw:
            return self._build_entries_from_raw(raw)

        return []
    
    def _write_entries(self, entries: list[MemoryEntry]) -> None:
        """将记忆条目列表写入文件"""
        self.global_path.parent.mkdir(parents=True, exist_ok=True)
        self.global_path.write_text(self._serialize_entries(entries), encoding="utf-8")

    def _serialize_entries(self, entries: list[MemoryEntry]) -> str:
        """将记忆条目列表转换为字符串"""
        return "\n\n".join(self._serialize_entry(entry) for entry in entries)

    def _serialize_entry(self, entry: MemoryEntry) -> str:
        metadata = {
            "id": entry.id,
            "kind": entry.kind,
            "updated_at": entry.updated_at,
        }
        return "\n".join(
            [
                f"{ENTRY_MARKER_PREFIX}{json.dumps(metadata, ensure_ascii=False)}{ENTRY_MARKER_SUFFIX}",
                entry.content.strip(),
            ]
        )

    def _render_entries(self, entries: list[MemoryEntry]) -> str:
        if not entries:
            return ""
        lines = ["Global memory:"]
        for entry in entries:
            lines.append(
                f"- [#{entry.id} {entry.kind} updated {self._parse_date(entry.updated_at)}] {entry.content}"
            )
        return "\n".join(lines)
    
    def _build_entries_from_raw(self, raw: str) -> list[MemoryEntry]:
        """按 marker 解析记忆条目列表"""
        entries = []
        last_entry_metadata = None
        last_entry_content_lines = []

        for line in raw.splitlines():
            current_entry_metadata = self._parse_metadata_from_marker_line(line.strip())
            if current_entry_metadata is not None:
                entry = self._build_entry_from_metadata(
                    last_entry_metadata,
                    "\n".join(last_entry_content_lines).strip()
                )
                if entry:
                    entries.append(entry)
                last_entry_metadata = current_entry_metadata
                last_entry_content_lines = []

            elif last_entry_metadata is not None:
                last_entry_content_lines.append(line)

        entry = self._build_entry_from_metadata(
            last_entry_metadata,
            "\n".join(last_entry_content_lines).strip()
        )
        if entry:
            entries.append(entry)

        return entries
    
    def _build_entry_from_metadata(
        self,
        metadata: dict | None,
        content: str
    ) -> MemoryEntry | None:
        if metadata is None or not content:
            return None

        entry_id = metadata.get("id")
        self._validate_id(entry_id)

        kind = metadata.get("kind")
        self._validate_kind(kind)

        updated_at = metadata.get("updated_at") or get_local_time().isoformat()

        return MemoryEntry(
            id=entry_id,
            kind=kind,
            content=content,
            updated_at=updated_at,
        )
    
    # === parse ===
    def _parse_metadata_from_marker_line(self, line: str) -> dict | None:
        """从 marker 行中解析出记忆条目 metadata"""
        if not line.startswith(ENTRY_MARKER_PREFIX) or not line.endswith(ENTRY_MARKER_SUFFIX):
            return None
        payload = line[len(ENTRY_MARKER_PREFIX):-len(ENTRY_MARKER_SUFFIX)].strip()
        try:
            metadata = json.loads(payload)
        except json.JSONDecodeError:
            return None
        return metadata if isinstance(metadata, dict) else None

    def _parse_date(self, date: str) -> str | None:
        """解析日期字符串, 将 isoformat 转换为 YYYY-MM-DD 格式"""
        if not isinstance(date, str):
            return None
        try:
            return datetime.fromisoformat(date).date().isoformat()
        except ValueError:
            return None

    # === validate ===
    def _validate_id(self, entry_id: int) -> None:
        """验证记忆条目 id 为正整数"""
        if not isinstance(entry_id, int) or entry_id <= 0:
            raise MemoryStoreError("id must be a positive integer.")

    def _validate_kind(self, kind: str) -> None:
        """验证记忆条目为有效类型"""
        if kind not in VALID_MEMORY_KINDS:
            raise MemoryStoreError("kind must be one of: preference, fact.")

    def _validate_content(self, content: str) -> None:
        """验证记忆内容非空"""
        if not content:
            raise MemoryStoreError("Memory content must not be empty.")
    
    # === utils ===
    def _find_index_by_id(self, entries: list[MemoryEntry], entry_id: int) -> int | None:
        for index, entry in enumerate(entries):
            if entry.id == entry_id:
                return index
        return None

    def _next_id(self, entries: list[MemoryEntry]) -> int:
        return max((entry.id for entry in entries), default=0) + 1

    def _result(self, message: str, **kwargs) -> MemoryResult:
        """返回记忆操作状态

        Args:
            message (str): 操作状态消息
            **kwargs: 其他附加信息
        """
        entries = self._get_entries()
        snapshot = self.read_global_memory_snapshot()

        return MemoryResult(
            message=message,
            path=snapshot.path,
            content=snapshot.content,
            entries=entries,
            truncated=snapshot.truncated,
            original_length=snapshot.original_length,
            **kwargs,
        )

    @contextmanager
    def _file_lock(self):
        lock_path = self.global_path.with_suffix(self.global_path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            with exclusive_file_lock(lock_file):
                yield
