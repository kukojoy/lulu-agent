from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


_session_workspaces: dict[str, Path] = {}
_current_session_id: ContextVar[str | None] = ContextVar("lulu_current_session_id", default=None)


@dataclass(frozen=True)
class WorkspaceStatus:
    path: Path | None
    message: str | None = None

    @property
    def available(self) -> bool:
        return self.message is None


def set_session_workspace(session_id: str | None, workspace: str | Path | None) -> Path:
    cwd = resolve_workspace(workspace)
    if session_id:
        _session_workspaces[session_id] = cwd
    return cwd


def current_session_workspace() -> Path:
    session_id = _current_session_id.get()
    if session_id:
        workspace = _session_workspaces.get(session_id)
        if workspace is not None:
            return resolve_workspace(workspace)
    return Path.cwd().expanduser().resolve()


def resolve_workspace(workspace: str | Path | None) -> Path:
    root = Path(workspace or Path.cwd()).expanduser().resolve()
    if not root.exists():
        raise ValueError(f"Workspace not found: {root}")
    if not root.is_dir():
        raise ValueError(f"Workspace is not a directory: {root}")
    return root


def get_workspace_status(workspace: str | Path | None) -> WorkspaceStatus:
    if workspace is None or not str(workspace).strip():
        return WorkspaceStatus(
            path=None,
            message="Session workspace is not configured.",
        )

    try:
        root = Path(workspace).expanduser().resolve()
        if not root.exists():
            return WorkspaceStatus(
                path=root,
                message=f"Workspace not found: {root}",
            )
        if not root.is_dir():
            return WorkspaceStatus(
                path=root,
                message=f"Workspace is not a directory: {root}",
            )
        if not os.access(root, os.R_OK | os.X_OK):
            return WorkspaceStatus(
                path=root,
                message=f"Workspace is not accessible: {root}",
            )
    except (OSError, RuntimeError) as exc:
        return WorkspaceStatus(
            path=None,
            message=f"Workspace is not accessible: {workspace} ({exc})",
        )

    return WorkspaceStatus(path=root)


@contextmanager
def activate_session(session_id: str | None) -> Iterator[str | None]:
    token = _current_session_id.set(session_id)
    try:
        yield session_id
    finally:
        _current_session_id.reset(token)
