from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def parse_jsonl_record(
    path: Path,
    line_number: int,
    line: str,
) -> dict[str, Any]:
    try:
        record = json.loads(line)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSONL record at {path}:{line_number}: {exc.msg}") from exc

    if not isinstance(record, dict):
        raise RuntimeError(f"Invalid JSONL record at {path}:{line_number}: expected object.")
    return record


def is_safe_session_id(session_id: str) -> bool:
    return bool(session_id) and all(
        char.isalnum() or char in {"-", "_"} for char in session_id
    )
