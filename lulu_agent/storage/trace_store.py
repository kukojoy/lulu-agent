import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from lulu_agent.runtime.events import RuntimeEvent
from lulu_agent.storage.jsonl import parse_jsonl_record


DEFAULT_TRACES_DIR = Path(".lulu") / "traces"


class TraceStoreError(RuntimeError):
    pass


class TraceStore:
    def __init__(self, root: Path | str = DEFAULT_TRACES_DIR):
        self.root = Path(root)
        self._write_lock = threading.Lock()

    def append_event(self, session_id: str, event: RuntimeEvent) -> dict[str, Any]:
        now = _local_now()
        record = {
            "type": "event",
            "session_id": session_id,
            "turn_id": event.turn_id,
            "created_at": now.isoformat(),
            "event_type": event.type,
            "timestamp": event.timestamp,
            "payload": event.payload,
        }

        with self._write_lock:
            self._ensure_root()
            path = self._trace_path(session_id)
            with path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(record, ensure_ascii=False))
                file.write("\n")
                file.flush()

        return record

    def load_events(
        self,
        session_id: str,
        turn_id: str | None = None,
    ) -> list[dict[str, Any]]:
        path = self._trace_path(session_id)
        if not path.exists():
            return []

        events: list[dict[str, Any]] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            record = parse_jsonl_record(path, line_number, line)
            _validate_trace_record(path, line_number, record, session_id)
            if turn_id is not None and record.get("turn_id") != turn_id:
                continue
            events.append(record)
        return events

    def _ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def _trace_path(self, session_id: str) -> Path:
        if not _is_safe_session_id(session_id):
            raise TraceStoreError(f"Invalid session id: {session_id}")
        return self.root / f"{session_id}.jsonl"


def _local_now() -> datetime:
    return datetime.now().astimezone()


def _validate_trace_record(
    path: Path,
    line_number: int,
    record: dict[str, Any],
    session_id: str,
) -> None:
    if record.get("type") != "event":
        raise TraceStoreError(
            f"Invalid trace record at {path}:{line_number}: type must be event."
        )
    if record.get("session_id") != session_id:
        raise TraceStoreError(
            f"Invalid trace record at {path}:{line_number}: session_id mismatch."
        )
    if not isinstance(record.get("turn_id"), str) or not record.get("turn_id"):
        raise TraceStoreError(
            f"Invalid trace record at {path}:{line_number}: turn_id must be a non-empty string."
        )
    if not isinstance(record.get("event_type"), str) or not record.get("event_type"):
        raise TraceStoreError(
            f"Invalid trace record at {path}:{line_number}: event_type must be a non-empty string."
        )
    if not isinstance(record.get("payload"), dict):
        raise TraceStoreError(
            f"Invalid trace record at {path}:{line_number}: payload must be an object."
        )


def _is_safe_session_id(session_id: str) -> bool:
    return bool(session_id) and all(
        char.isalnum() or char in {"-", "_"} for char in session_id
    )
