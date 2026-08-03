from __future__ import annotations

from typing import Any

from lulu_agent.safety.policy import (
    PATH_OPERATION_READ,
    PATH_OPERATION_WRITE,
    SAFETY_DENY,
    PathOperation,
    PathSafetyError,
    SafetyDecision,
    check_path_operation_safety,
    check_shell_command_safety,
)


TOOL_PATH_OPERATIONS: dict[str, tuple[str, PathOperation, str | None]] = {
    "read_file": ("path", PATH_OPERATION_READ, None),
    "list_files": ("path", PATH_OPERATION_READ, "."),
    "search_text": ("path", PATH_OPERATION_READ, "."),
    "write_file": ("path", PATH_OPERATION_WRITE, None),
    "replace_in_file": ("path", PATH_OPERATION_WRITE, None),
}


def check_tool_call_safety(
    tool_name: str,
    arguments: dict[str, Any],
    safety_profile: str,
) -> SafetyDecision | None:
    if tool_name == "run_shell":
        return _check_shell_command_tool_call_safety(arguments["command"], safety_profile=safety_profile)

    path_policy = TOOL_PATH_OPERATIONS.get(tool_name)
    if path_policy is None:
        return None
    path_argument, operation, default_path = path_policy
    raw_path = arguments.get(path_argument) or default_path
    if raw_path is None:
        return None
    return _check_path_tool_call_safety(raw_path, operation, safety_profile)


def _check_shell_command_tool_call_safety(
    command: str,
    safety_profile: str,
) -> SafetyDecision:
    return check_shell_command_safety(command, safety_profile=safety_profile)


def _check_path_tool_call_safety(
    raw_path: str,
    operation: PathOperation,
    safety_profile: str,
) -> SafetyDecision:
    try:
        decision = check_path_operation_safety(
            raw_path,
            operation=operation,
            safety_profile=safety_profile,
        )
    except PathSafetyError as exc:
        return SafetyDecision(
            decision=SAFETY_DENY,
            reason=exc.error_message,
            category="file_path",
        )
    return decision
