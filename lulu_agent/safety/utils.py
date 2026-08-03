from pathlib import Path


def resolve_path(
    path: str | Path,
    workspace_root: str | Path | None = None,
) -> Path:
    """路径解析函数, 绝对路径直接返回, 相对路径拼接到工作路径后再转为绝对路径"""
    root = Path.cwd() if workspace_root is None else Path(workspace_root)
    root = root.expanduser().resolve()

    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate.resolve()
