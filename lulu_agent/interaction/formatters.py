from typing import Any


def format_sessions(sessions: list[dict[str, Any]]) -> str:
    if not sessions:
        return "No sessions found."

    lines = ["Recent sessions:"]
    for session in sessions:
        title = session.get("title") or "(untitled)"
        cwd = session.get("cwd") or ""
        lines.append(
            f"- {session.get('session_id')} updated={session.get('updated_at')} "
            f"messages={session.get('message_count', 0)} title={title} cwd={cwd}"
        )
    return "\n".join(lines)


def format_session_inspection(summary: dict[str, Any]) -> str:
    metadata = summary["metadata"]
    lines = [
        f"Session: {metadata.get('session_id')}",
        f"Updated: {metadata.get('updated_at')}",
        f"Cwd: {metadata.get('cwd')}",
        f"Title: {metadata.get('title') or '(untitled)'}",
        f"Messages: {summary['message_count']}",
        f"Turns: {summary.get('turn_count', 0)}",
        f"Compressions: {summary.get('compression_count', 0)}",
        f"Task states: {summary.get('task_state_count', 0)}",
        "Transcript summary:",
    ]
    for index, message in enumerate(summary["messages"], start=1):
        detail = message.get("content") or ""
        if message.get("has_tool_calls"):
            detail = f"{detail} [tool_calls]".strip()
        if message.get("tool_call_id"):
            detail = f"{detail} [tool_call_id={message['tool_call_id']}]".strip()
        if message.get("turn_id"):
            detail = f"{detail} [turn_id={message['turn_id']}]".strip()
        lines.append(f"{index}. {message.get('role')}: {detail}")
    if summary.get("turns"):
        lines.append("Turn summary:")
        for index, turn in enumerate(summary["turns"], start=1):
            detail = (
                f"{turn.get('status')} / {turn.get('exit_reason')} "
                f"model_calls={turn.get('model_calls', 0)} "
                f"tool_calls={turn.get('tool_calls', 0)}"
            )
            if turn.get("error"):
                error_type = turn.get("error_type")
                if error_type:
                    detail = f"{detail} error_type={error_type}"
                detail = f"{detail} error={turn['error']}"
            lines.append(f"{index}. {turn.get('turn_id')}: {detail}")
    if summary.get("compressions"):
        lines.append("Compression summary:")
        for index, compression in enumerate(summary["compressions"], start=1):
            turns = ", ".join(compression.get("covered_turn_ids") or [])
            detail = (
                f"{compression.get('scope')} turns=[{turns}] "
                f"source_prompt_chars={compression.get('source_prompt_chars', 0)} "
                f"summary_chars={compression.get('summary_chars', 0)} "
                f"summary_tokens={compression.get('summary_tokens', 0)}"
            )
            lines.append(f"{index}. {compression.get('compression_id')}: {detail}")
    if summary.get("task_state"):
        task_state = summary["task_state"]
        lines.append("Task state:")
        lines.append(f"Goal: {task_state.get('goal')}")
        lines.append(f"Status: {task_state.get('status')}")
        if task_state.get("next_action"):
            lines.append(f"Next action: {task_state['next_action']}")
    return "\n".join(lines)


def format_context_inspection(session_id: str, inspection: dict[str, Any]) -> str:
    lines = [
        f"Context inspection: {session_id}",
        f"Messages: {inspection.get('message_count', 0)}",
        f"Total chars: {inspection.get('total_chars', 0)}",
        f"System chars: {inspection.get('system_chars', 0)}",
        "Runtime environment block is only available during active turns.",
    ]
    blocks = inspection.get("context_blocks") or []
    if blocks:
        lines.append("Context blocks:")
        for block in blocks:
            lines.append(f"- {block.get('name')}: chars={block.get('chars', 0)}")
    raw_turn_ids = inspection.get("raw_turn_ids") or []
    if raw_turn_ids:
        lines.append("Raw turns:")
        for turn_id in raw_turn_ids:
            lines.append(f"- {turn_id}")
    compressed_turn_ids = inspection.get("compressed_turn_ids") or []
    compression_ids = inspection.get("compression_ids") or []
    if compressed_turn_ids:
        lines.append("Compressed turns:")
        lines.append(f"- turn_ids: {', '.join(compressed_turn_ids)}")
        if compression_ids:
            lines.append(f"- compression_ids: {', '.join(compression_ids)}")
    system_message = inspection.get("system_message") or ""
    if system_message:
        lines.extend(
            [
                "System message:",
                str(system_message),
            ]
        )
    return "\n".join(lines)
