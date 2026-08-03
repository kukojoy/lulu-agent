import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from lulu_agent.runtime.errors import ERROR_PERMISSION_DENIED, LuluError
from lulu_agent.safety.utils import resolve_path


class SafetyDecisionType(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    NEEDS_APPROVAL = "needs_approval"


SAFETY_ALLOW = SafetyDecisionType.ALLOW
SAFETY_DENY = SafetyDecisionType.DENY
SAFETY_NEEDS_APPROVAL = SafetyDecisionType.NEEDS_APPROVAL
SAFETY_DECISIONS = frozenset(SafetyDecisionType)


class SandboxMode(StrEnum):
    NONE = "none"
    SOFT_WORKSPACE = "soft_workspace"
    OS = "os_sandbox"


SANDBOX_NONE = SandboxMode.NONE
SANDBOX_SOFT_WORKSPACE = SandboxMode.SOFT_WORKSPACE
SANDBOX_OS = SandboxMode.OS
CURRENT_SANDBOX_MODE = SANDBOX_SOFT_WORKSPACE


class SafetyProfile(StrEnum):
    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    APPROVAL_REQUIRED = "approval_required"
    TRUSTED = "trusted"


SAFETY_PROFILE_READ_ONLY = SafetyProfile.READ_ONLY
SAFETY_PROFILE_WORKSPACE_WRITE = SafetyProfile.WORKSPACE_WRITE
SAFETY_PROFILE_APPROVAL_REQUIRED = SafetyProfile.APPROVAL_REQUIRED
SAFETY_PROFILE_TRUSTED = SafetyProfile.TRUSTED
DEFAULT_SAFETY_PROFILE = SAFETY_PROFILE_WORKSPACE_WRITE
SAFETY_PROFILES = frozenset(SafetyProfile)


class PathOperation(StrEnum):
    READ = "read"
    WRITE = "write"


PATH_OPERATION_READ = PathOperation.READ
PATH_OPERATION_WRITE = PathOperation.WRITE
PATH_OPERATIONS = frozenset(PathOperation)

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
    (re.compile(r"\brm\s+(?:[^\s;&|]+\s+)*-[^\s;&|]*r[^\s;&|]*f[^\s;&|]*\b"), "recursive forced delete"),
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
    decision: SafetyDecisionType
    reason: str
    category: str = "unknown"

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "decision", SafetyDecisionType(self.decision))
        except ValueError as exc:
            raise ValueError(f"Invalid safety decision: {self.decision}") from exc
        if not self.reason:
            raise ValueError("Safety decision reason must not be empty")
        if not self.category:
            raise ValueError("Safety decision category must not be empty")


class SafetyPolicyError(LuluError):
    def __init__(self, error_message: str):
        super().__init__(error_message, ERROR_PERMISSION_DENIED)


class PathSafetyError(SafetyPolicyError):
    pass


# === 对外接口 ===
def validate_safety_profile(profile: str | SafetyProfile) -> SafetyProfile:
    try:
        return SafetyProfile(profile)
    except ValueError as exc:
        allowed = ", ".join(sorted(SafetyProfile))
        raise ValueError(f"Invalid safety profile: {profile}. Use one of: {allowed}.") from exc


def check_shell_command_safety(
    command: str,
    safety_profile: str | SafetyProfile = DEFAULT_SAFETY_PROFILE,
) -> SafetyDecision:
    """判断命令安全性
    
    Args:
        command (str): 要判断的 shell 命令
    
    Returns:
        SafetyDecision: 安全性判断结果
    """
    safety_profile = validate_safety_profile(safety_profile)

    for pattern, reason in SHELL_DENY_PATTERNS:
        if pattern.search(command):
            return SafetyDecision(
                decision=SAFETY_DENY,
                reason=reason,
                category="shell_command",
            )

    if safety_profile == SAFETY_PROFILE_READ_ONLY:
        return SafetyDecision(
            decision=SAFETY_DENY,
            reason="safety profile read_only does not allow shell commands",
            category="shell_command",
        )

    if safety_profile == SAFETY_PROFILE_APPROVAL_REQUIRED:
        return SafetyDecision(
            decision=SAFETY_NEEDS_APPROVAL,
            reason="safety profile approval_required requires approval for shell commands",
            category="shell_command",
        )

    if safety_profile == SAFETY_PROFILE_TRUSTED:
        return SafetyDecision(
            decision=SAFETY_ALLOW,
            reason="safety profile trusted allows shell commands",
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


def check_path_operation_safety(
    path: str | Path,
    workspace_root: str | Path | None = None,
    operation: str | PathOperation = PATH_OPERATION_READ,
    safety_profile: str | SafetyProfile = DEFAULT_SAFETY_PROFILE,
) -> SafetyDecision:
    safety_profile = validate_safety_profile(safety_profile)
    operation = PathOperation(operation)

    resolved = resolve_path(path, workspace_root=workspace_root)
    _ensure_not_sensitive_path(resolved, operation)

    if operation == PATH_OPERATION_WRITE:
        _ensure_path_operation_allowed(operation, safety_profile)
        if safety_profile == SAFETY_PROFILE_WORKSPACE_WRITE and _is_outside_workspace(resolved, workspace_root):
            return SafetyDecision(
                decision=SAFETY_NEEDS_APPROVAL,
                reason=f"writing outside workspace root: {resolved}",
                category="file_path",
            )

    return SafetyDecision(
        decision=SAFETY_ALLOW,
        reason="path operation allowed",
        category="file_path",
    )


# === helpers ===
def _is_outside_workspace(path: Path, workspace_root: str | Path | None = None) -> bool:
    root = Path.cwd() if workspace_root is None else Path(workspace_root)
    root = root.expanduser().resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return True
    return False


def _ensure_not_sensitive_path(path: Path, operation: PathOperation) -> None:
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


def _ensure_path_operation_allowed(operation: PathOperation, safety_profile: SafetyProfile) -> None:
    """检查路径操作是否允许"""
    if operation != PATH_OPERATION_WRITE:
        return

    if safety_profile == SAFETY_PROFILE_READ_ONLY:
        raise PathSafetyError("Safety profile read_only does not allow workspace writes.")

    if safety_profile == SAFETY_PROFILE_APPROVAL_REQUIRED:
        raise PathSafetyError(
            "Workspace write requires approval, but no approval provider is available."
        )
