import re
from dataclasses import dataclass
from pathlib import Path


SAFETY_ALLOW = "allow"
SAFETY_DENY = "deny"
SAFETY_NEEDS_APPROVAL = "needs_approval"
SAFETY_DECISIONS = {
    SAFETY_ALLOW,
    SAFETY_DENY,
    SAFETY_NEEDS_APPROVAL,
}

SANDBOX_SOFT_WORKSPACE = "soft_workspace"
SANDBOX_NONE = "none"
SANDBOX_OS = "os_sandbox"
CURRENT_SANDBOX_MODE = SANDBOX_SOFT_WORKSPACE

PATH_OPERATION_READ = "read"
PATH_OPERATION_WRITE = "write"
PATH_OPERATIONS = {
    PATH_OPERATION_READ,
    PATH_OPERATION_WRITE,
}

PROJECT_SECRET_BASENAMES = {
    ".env",
    ".env.local",
    ".env.development",
    ".env.production",
    ".env.test",
    ".env.staging",
    ".envrc",
}
SENSITIVE_WRITE_DIR_NAMES = {
    ".ssh",
    ".aws",
    ".gnupg",
    ".kube",
}
SHELL_DENY_PATTERNS = [
    (re.compile(r"\brm\s+.*-[^\s]*r[^\s]*f"), "recursive forced delete"),
    (re.compile(r"\bsudo\b"), "sudo command"),
    (re.compile(r">\s*/(?:etc|bin|sbin|usr|var|System|Library)\b"), "redirect to system path"),
    (re.compile(r"\b(curl|wget)\b.*\|\s*(sh|bash)\b"), "download and execute shell script"),
]
SHELL_APPROVAL_PATTERNS = [
    (re.compile(r"\brm\s+"), "remove file or directory"),
    (re.compile(r"\bmv\s+"), "move or rename file"),
    (re.compile(r"\bchmod\s+"), "change file permissions"),
    (re.compile(r"\bchown\s+"), "change file owner"),
]


@dataclass(frozen=True)
class SafetyDecision:
    decision: str
    reason: str
    category: str = "unknown"

    def __post_init__(self) -> None:
        if self.decision not in SAFETY_DECISIONS:
            raise ValueError(f"Invalid safety decision: {self.decision}")
        if not self.reason:
            raise ValueError("Safety decision reason must not be empty")
        if not self.category:
            raise ValueError("Safety decision category must not be empty")


class PathSafetyError(ValueError):
    pass


def validate_workspace_path(
    path: str | Path,
    workspace_root: str | Path | None = None,
    operation: str = PATH_OPERATION_READ,
) -> Path:
    """验证路径是否安全, 不安全则抛出异常"""
    resolved = resolve_workspace_path(
        path,
        workspace_root=workspace_root,
        operation=operation,
    )
    _ensure_not_sensitive_path(resolved, operation)
    return resolved


def resolve_workspace_path(
    path: str | Path,
    workspace_root: str | Path | None = None,
    operation: str = PATH_OPERATION_READ,
) -> Path:
    """将指定路径解析为工作区根目录下的绝对路径, 并确保该路径在工作区根目录内
    
    Args:
        path (str | Path): 要解析的路径
        workspace_root (str | Path | None): 工作区根目录
        operation (str): 路径操作类型, 当前可选值为 "read" 或 "write"
    
    Returns:
        Path: 解析后的绝对路径
    """

    if operation not in PATH_OPERATIONS:
        raise ValueError(f"Invalid path operation: {operation}")

    root = Path.cwd() if workspace_root is None else Path(workspace_root)
    root = root.expanduser().resolve() # root 的绝对路径

    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    resolved = candidate.resolve()

    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PathSafetyError(
            f"Path escapes workspace root: {resolved} is outside {root}"
        ) from exc

    return resolved


def _ensure_not_sensitive_path(path: Path, operation: str) -> None:
    """检查路径目标是否敏感, 是则抛出异常"""
    if path.name in PROJECT_SECRET_BASENAMES:
        raise PathSafetyError(
            f"Refused to {operation} sensitive project file: {path.name}"
        )

    if operation == PATH_OPERATION_WRITE:
        for part in path.parts:
            if part in SENSITIVE_WRITE_DIR_NAMES:
                raise PathSafetyError(
                    f"Refused to write sensitive directory path: {part}"
                )


def classify_shell_command(command: str) -> SafetyDecision:
    """判断命令安全性
    
    Args:
        command (str): 要判断的 shell 命令
    
    Returns:
        SafetyDecision: 安全性判断结果
    """

    for pattern, reason in SHELL_DENY_PATTERNS:
        if pattern.search(command):
            return SafetyDecision(
                decision=SAFETY_DENY,
                reason=reason,
                category="shell_command",
            )

    for pattern, reason in SHELL_APPROVAL_PATTERNS:
        if pattern.search(command):
            return SafetyDecision(
                decision=SAFETY_NEEDS_APPROVAL,
                reason=reason,
                category="shell_command",
            )

    return SafetyDecision(
        decision=SAFETY_ALLOW,
        reason="command did not match risky shell patterns",
        category="shell_command",
    )
