"""Runtime-level helpers that are shared by runtime models and sinks."""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import IO, Iterator


def get_local_time() -> datetime:
    return datetime.now().astimezone()


def resolve_path(path: str | Path, root: str | Path) -> Path:
    """路径解析: 若 path 为绝对路径, 直接返回; 若 path 为相对路径, 拼接到 root 后返回"""
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path(root).expanduser() / candidate
    return candidate.resolve()


if os.name == "nt":
    import msvcrt
else:
    import fcntl


@contextmanager
def exclusive_file_lock(file: IO[str]) -> Iterator[None]:
    if os.name == "nt":
        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            file.seek(0)
            msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
        return

    fcntl.flock(file.fileno(), fcntl.LOCK_EX)
    try:
        yield
    finally:
        fcntl.flock(file.fileno(), fcntl.LOCK_UN)
