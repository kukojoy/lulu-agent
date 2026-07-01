import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


DEFAULT_SESSIONS_DIR = Path(".lulu") / "sessions"
SESSION_INDEX_FILENAME = "sessions_index.jsonl"
TITLE_MAX_CHARS = 60


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
        now = _utc_now()
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

    def append_message(self, session_id: str, message: dict[str, Any]) -> dict[str, Any]:
        """向指定 session 追加一条消息, 并更新 session metadata
        
        Returns:
            dict[str, Any]: 更新后的 session metadata
        """
        self._ensure_root()
        path = self._existing_session_path(session_id)
        now = _utc_now()
        
        metadata = self._metadata_for_append(session_id, message, now)

        record = {
            "type": "message",
            "session_id": session_id,
            "created_at": now.isoformat(),
            "message": message,
        }

        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False))
            file.write("\n")
            file.flush()

        # metadata 构造成功且消息写入成功后, 再将 metadata 写入 index 文件
        self.append_index(metadata)

        return metadata

    def append_index(self, metadata: dict[str, Any]) -> None:
        """向 session index 文件追加一条 metadata 记录"""
        self._ensure_root()
        with self.index_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(metadata, ensure_ascii=False))
            file.write("\n")
            file.flush()

    def load_messages(self, session_id: str) -> list[dict[str, Any]]:
        """加载指定 session 的所有消息
        
        Returns:
            list[dict[str, Any]]: session id 对应的 msg 列表
        """
        path = self._existing_session_path(session_id)
        messages: list[dict[str, Any]] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            record = _parse_jsonl_record(path, line_number, line)
            if record.get("type") != "message":
                raise SessionStoreError(
                    f"Invalid session record at {path}:{line_number}: expected type 'message'."
                )
            if record.get("session_id") != session_id:
                raise SessionStoreError(
                    f"Invalid session record at {path}:{line_number}: session_id mismatch."
                )
            message = record.get("message")
            if not isinstance(message, dict):
                raise SessionStoreError(
                    f"Invalid session record at {path}:{line_number}: message must be an object."
                )
            messages.append(message)
        return messages

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

    def validate_session(self, session_id: str) -> None:
        """验证指定 session 是否存在, 是否能正常加载 metadata 和消息"""
        self._get_latest_metadata_for_session(session_id)
        self.load_messages(session_id)

    def inspect_session(self, session_id: str) -> dict[str, Any]:
        """获取指定 session 的 metadata, 消息数量和消息列表 (部分字段)"""
        metadata = self._get_latest_metadata_for_session(session_id)
        messages = self.load_messages(session_id)
        return {
            "metadata": metadata,
            "message_count": len(messages),
            "messages": [
                {
                    "role": message.get("role"),
                    "content": _summarize_content(message.get("content")),
                    "has_tool_calls": bool(message.get("tool_calls")),
                    "tool_call_id": message.get("tool_call_id"),
                }
                for message in messages
            ],
        }

    def _metadata_for_append(
        self,
        session_id: str,
        message: dict[str, Any],
        updated_at: datetime,
    ) -> dict[str, Any]:
        """生成追加会话消息所需的 metadata, 包括更新 updated_at 和 message_count 字段, 以及根据消息内容生成 title (如果还未生成)
        
        Returns:
            dict[str, Any]: 更新后的 session metadata
        """
        metadata = self._get_latest_metadata_for_session(session_id)

        # 更新 updated_at 和 message_count 字段
        metadata["updated_at"] = updated_at.isoformat()
        metadata["message_count"] = int(metadata.get("message_count") or 0) + 1
        
        # 根据消息内容, 为 session 生成 title (如果之前没有的话)
        if not metadata.get("title"):
            title = _title_from_message(message)
            if title:
                metadata["title"] = title

        return metadata

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
            metadata: dict[str, Any] = _parse_jsonl_record(self.index_path, line_number, line)
            session_id = metadata.get("session_id")
            if not isinstance(session_id, str) or not session_id:
                raise SessionStoreError(
                    f"Invalid session index record at {self.index_path}:{line_number}: "
                    "session_id must be a non-empty string."
                )
            latest[session_id] = metadata
        return latest

    def _ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def _session_path(self, session_id: str) -> Path:
        """构造 session id path"""
        if not _is_safe_session_id(session_id):
            raise SessionStoreError(f"Invalid session id: {session_id}")
        return self.root / f"{session_id}.jsonl"

    def _existing_session_path(self, session_id: str) -> Path:
        """检验 session id path 是否存在, 并返回对应路径"""
        path = self._session_path(session_id)
        if not path.exists():
            raise SessionStoreError(f"Session not found: {session_id}")
        return path


def _utc_now() -> datetime:
    """获取当前 UTC 时间"""
    return datetime.now(timezone.utc)


def _new_session_id(created_at: datetime) -> str:
    """获取一个新的 session id, 格式: session-YYYYMMDD-HHMMSS-XXXXXXXX"""
    timestamp = created_at.strftime("%Y%m%d-%H%M%S")
    return f"session-{timestamp}-{uuid4().hex[:8]}"


def _parse_jsonl_record(path: Path, line_number: int, line: str) -> dict[str, Any]:
    """将读取到的 metadata/message JSONL line 解析为 dict"""
    try:
        record = json.loads(line)
    except json.JSONDecodeError as exc:
        raise SessionStoreError(
            f"Invalid JSONL record at {path}:{line_number}: {exc.msg}"
        ) from exc

    if not isinstance(record, dict):
        raise SessionStoreError(
            f"Invalid JSONL record at {path}:{line_number}: expected object."
        )
    return record


def _is_safe_session_id(session_id: str) -> bool:
    """检查 session id 是否合法 (仅包含字母, 数字, - 和 _)"""
    return bool(session_id) and all(
        char.isalnum() or char in {"-", "_"} for char in session_id
    )


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
