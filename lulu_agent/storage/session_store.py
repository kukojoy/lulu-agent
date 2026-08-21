import json
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4

from lulu_agent.runtime.session.compression import Compression
from lulu_agent.runtime.session.message import Message
from lulu_agent.runtime.session.model import SessionRuntimeModel
from lulu_agent.runtime.session.task_state import TaskState
from lulu_agent.runtime.session.turn import Turn
from lulu_agent.runtime.utils import get_local_time
from lulu_agent.storage.session_record import SessionRecord, SessionRecordType
from lulu_agent.storage.utils import is_safe_session_id, parse_jsonl_record


DEFAULT_SESSIONS_DIR = Path(".lulu") / "sessions"
SESSION_INDEX_FILENAME = "sessions_index.jsonl"
TITLE_MAX_CHARS = 60
TURN_SUMMARY_MAX_RESPONSE_CHARS = 240
COMPRESSION_SUMMARY_MAX_CHARS = 500
T = TypeVar("T", bound=SessionRuntimeModel)


class SessionStoreError(RuntimeError):
    pass


class SessionStore:
    def __init__(self, root: Path | str = DEFAULT_SESSIONS_DIR):
        self.root = Path(root)
        self.index_path = self.root / SESSION_INDEX_FILENAME

    def create_session(self, cwd: Path | str | None = None, title: str = "") -> dict[str, Any]:
        """创建一个新的 session
        
        Returns:
            dict[str, Any]: session metadata
        """
        self._ensure_root()
        now = get_local_time()
        session_id = _new_session_id(now)
        metadata = {
            "session_id": session_id,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "cwd": str(Path(cwd or ".").resolve()),
            "title": title,
            "message_count": 0,
        }
        self._session_path(session_id).touch(exist_ok=False)
        self.append_index(metadata)
        return metadata

    def append_record(self, record: SessionRecord) -> dict[str, Any]:
        """向指定 session 追加一条 record, 并更新 session metadata"""
        self._ensure_root()
        path = self._existing_session_path(record.session_id)
        metadata = self._metadata_for_record_append(record)

        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record.to_dict(), ensure_ascii=False))
            file.write("\n")
            file.flush()

        self.append_index(metadata)
        return metadata

    def append_index(self, metadata: dict[str, Any]) -> None:
        """向 session index 文件追加一条 metadata 记录"""
        self._ensure_root()
        with self.index_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(metadata, ensure_ascii=False))
            file.write("\n")
            file.flush()

    def load_messages(self, session_id: str) -> list[Message]:
        """加载指定 session 的所有消息
        
        Returns:
            list[Message]: session id 对应的消息列表
        """
        return self._load_records(session_id=session_id, model_cls=Message)

    def load_turns(self, session_id: str) -> list[Turn]:
        """加载指定 session 的所有 turn 摘要"""
        return self._load_records(session_id=session_id, model_cls=Turn)

    def load_compressions(self, session_id: str) -> list[Compression]:
        """加载指定 session 的所有 compression 记录"""
        return self._load_records(session_id=session_id, model_cls=Compression)

    def load_task_states(self, session_id: str) -> list[TaskState]:
        """加载指定 session 的所有 task state 记录"""
        return self._load_records(session_id=session_id, model_cls=TaskState)

    def load_latest_task_state(self, session_id: str) -> TaskState | None:
        """加载指定 session 的最新 task state"""
        task_states = self.load_task_states(session_id)
        if not task_states:
            return None
        return task_states[-1]

    def list_sessions(self, limit: int | None = None) -> list[dict[str, Any]]:
        """列出所有 session 的最新 metadata, 按 updated_at 降序排列
        Args:
            limit (int | None): 限制返回的 session 数量, 如果为 None 则返回所有 session

        Returns:
            list[dict[str, Any]]: 最新的 session metadata 列表
        """
        latest: dict[str, dict[str, Any]] = self._get_latest_metadatas_from_index()
        sessions = sorted(
            latest.values(),
            key=lambda metadata: metadata.get("updated_at", ""),
            reverse=True,
        )
        if limit is None:
            return sessions
        return sessions[:limit]

    def delete_session(self, session_id: str) -> dict[str, Any]:
        """删除指定 session 文件, 并从 session index 中移除对应 metadata"""
        metadata = self._get_latest_metadata_for_session(session_id)
        path = self._existing_session_path(session_id)
        path.unlink()
        self._rewrite_index_without_session(session_id)
        return metadata

    def validate_session(self, session_id: str) -> None:
        """验证指定 session 是否存在, 是否能正常加载 metadata, 消息和 turns"""
        self._get_latest_metadata_for_session(session_id)
        self.load_messages(session_id)
        self.load_turns(session_id)
        self.load_compressions(session_id)
        self.load_task_states(session_id)

    def inspect_session(self, session_id: str) -> dict[str, Any]:
        """获取指定 session 的 metadata, 消息数量和消息列表 (部分字段)"""
        metadata = self._get_latest_metadata_for_session(session_id)
        messages = self.load_messages(session_id)
        turns = self.load_turns(session_id)
        compressions = self.load_compressions(session_id)
        task_states = self.load_task_states(session_id)
        latest_task_state = task_states[-1] if task_states else None
        return {
            "metadata": metadata,
            "message_count": len(messages),
            "turn_count": len(turns),
            "compression_count": len(compressions),
            "task_state_count": len(task_states),
            "task_state": latest_task_state.to_dict() if latest_task_state else None,
            "messages": [
                {
                    "role": message.role,
                    "content": _summarize_content(message.content),
                    "has_tool_calls": bool(message.tool_calls),
                    "tool_call_id": message.tool_call_id,
                    "turn_id": message.turn_id,
                }
                for message in messages
            ],
            "turns": [turn.to_dict() for turn in turns[-10:]],
            "compressions": [compression.to_dict() for compression in compressions[-10:]],
        }

    def _metadata_for_record_append(
        self,
        record: SessionRecord,
    ) -> dict[str, Any]:
        metadata = self._get_latest_metadata_for_session(record.session_id)
        metadata["updated_at"] = get_local_time().isoformat()
        if record.type == SessionRecordType.MESSAGE:
            metadata["message_count"] = int(metadata.get("message_count") or 0) + 1
            title = _title_from_message(record.data)
            if title and not metadata.get("title"):
                metadata["title"] = title
        return metadata

    def _load_records(
        self,
        session_id: str,
        model_cls: type[T],
    ) -> list[T]:
        path = self._existing_session_path(session_id)
        records: list[T] = []
        expected_type = model_cls.type
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            raw_record = parse_jsonl_record(path, line_number, line)
            try:
                record = SessionRecord.from_dict(raw_record)
            except ValueError as exc:
                raise SessionStoreError(f"Invalid session record at {path}:{line_number}: {exc}") from exc
            if record.type != expected_type:
                continue
            if record.session_id != session_id:
                raise SessionStoreError(
                    f"Invalid session record at {path}:{line_number}: session_id mismatch."
                )

            try:
                records.append(model_cls.from_record(record))
            except ValueError as exc:
                raise SessionStoreError(f"Invalid session record at {path}:{line_number}: {exc}") from exc
        return records

    def _get_latest_metadata_for_session(self, session_id: str) -> dict[str, Any]:
        """获取指定 session 的最新 metadata"""
        latest_metadata = self._get_latest_metadatas_from_index().get(session_id)
        if latest_metadata is None:
            raise SessionStoreError(f"Session metadata not found: {session_id}")
        return latest_metadata

    def _get_latest_metadatas_from_index(self) -> dict[str, dict[str, Any]]:
        """从 session index 文件中获取每个 session 的最新 metadata
        
        Returns:
            dict[str, dict[str, Any]]: session_id -> metadata
        """
        if not self.index_path.exists():
            return {}

        latest: dict[str, dict[str, Any]] = {}
        # 遍历 + 覆盖
        for line_number, line in enumerate(
            self.index_path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not line.strip():
                continue
            metadata: dict[str, Any] = parse_jsonl_record(self.index_path, line_number, line)
            session_id = metadata.get("session_id")
            if not isinstance(session_id, str) or not session_id:
                raise SessionStoreError(
                    f"Invalid session index record at {self.index_path}:{line_number}: "
                    "session_id must be a non-empty string."
                )
            latest.pop(session_id, None)
            latest[session_id] = metadata
        return latest

    def _rewrite_index_without_session(self, session_id: str) -> None:
        """重写 session index 文件, 移除指定 session 的 metadata"""
        if not self.index_path.exists():
            return

        kept_lines: list[str] = []
        for line_number, line in enumerate(
            self.index_path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not line.strip():
                continue
            metadata: dict[str, Any] = parse_jsonl_record(self.index_path, line_number, line)
            record_session_id = metadata.get("session_id")
            if not isinstance(record_session_id, str) or not record_session_id:
                raise SessionStoreError(
                    f"Invalid session index record at {self.index_path}:{line_number}: "
                    "session_id must be a non-empty string."
                )
            if record_session_id != session_id:
                kept_lines.append(json.dumps(metadata, ensure_ascii=False))

        content = "\n".join(kept_lines)
        if content:
            content += "\n"
        self.index_path.write_text(content, encoding="utf-8")

    def _ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def _session_path(self, session_id: str) -> Path:
        """构造 session id path"""
        if not is_safe_session_id(session_id):
            raise SessionStoreError(f"Invalid session id: {session_id}")
        return self.root / f"{session_id}.jsonl"

    def _existing_session_path(self, session_id: str) -> Path:
        """检验 session id path 是否存在, 并返回对应路径"""
        path = self._session_path(session_id)
        if not path.exists():
            raise SessionStoreError(f"Session not found: {session_id}")
        return path


def _new_session_id(created_at: datetime) -> str:
    """获取一个新的 session id, 格式: session-YYYYMMDD-HHMMSS-XXXXXXXX"""
    timestamp = created_at.strftime("%Y%m%d-%H%M%S")
    return f"session-{timestamp}-{uuid4().hex[:8]}"


def _title_from_message(message: dict[str, Any]) -> str:
    """根据消息内容生成 title"""
    if message.get("role") != "user":
        return ""
    content = message.get("content")
    if not isinstance(content, str):
        return ""
    return _summarize_content(content, TITLE_MAX_CHARS)


def _summarize_content(content: Any, max_chars: int = 120) -> str:
    """压缩消息内容, 并截断到指定长度"""
    if not isinstance(content, str):
        return ""
    collapsed = " ".join(content.split())
    return collapsed[:max_chars]
