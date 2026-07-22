import argparse
from pathlib import Path

from lulu_agent.core.agent_loop import AgentLoop
from lulu_agent.runtime.cli_input import read_user_input, setup_line_editing
from lulu_agent.config import ConfigError
from lulu_agent.llm.client import LLMClient
from lulu_agent.runtime.event_sinks import CliEventSink, CompositeEventSink, PersistentEventSink
from lulu_agent.storage.session_store import SessionStore, SessionStoreError
from lulu_agent.storage.trace_store import TraceStore
from lulu_agent.memory.review import MemoryReviewer
from lulu_agent.skills.review import SkillReviewer
from lulu_agent.config import config
from lulu_agent.skills.utils import install_bundled_skills


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the lulu-agent CLI.")
    parser.add_argument(
        "--resume",
        metavar="SESSION_ID",
        help="Resume an existing session by id.",
    )
    parser.add_argument(
        "--list-sessions",
        action="store_true",
        help="List recent sessions and exit.",
    )
    parser.add_argument(
        "--inspect-session",
        metavar="SESSION_ID",
        help="Inspect one session and exit.",
    )
    return parser.parse_args(argv)


def create_agent(
    args: argparse.Namespace,
    session_store: SessionStore | None = None,
    llm_client: LLMClient | None = None,
    memory_reviewer: MemoryReviewer | None = None,
    skill_reviewer: SkillReviewer | None = None,
) -> tuple[AgentLoop, str]:
    store = session_store or SessionStore()
    if args.resume:
        session_id = args.resume
        store.validate_session(session_id)
    else:
        metadata = store.create_session(cwd=Path.cwd())
        session_id = metadata["session_id"]

    return AgentLoop(
        session_store=store,
        session_id=session_id,
        llm_client=llm_client,
        event_sink=CompositeEventSink(
            [
                CliEventSink(),
                PersistentEventSink(TraceStore(), session_id),
            ]
        ),
        memory_reviewer=memory_reviewer,
        skill_reviewer=skill_reviewer,
    ), session_id


def format_sessions(sessions: list[dict]) -> str:
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


def format_session_inspection(summary: dict) -> str:
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


def main(argv: list[str] | None = None):
    setup_line_editing()
    try:
        install_bundled_skills()
    except Exception as exc:
        print(f"[Skill bootstrap warning] {exc}")
        
    args = parse_args(argv)
    store = SessionStore()
    llm_client = LLMClient(config)
    memory_reviewer = MemoryReviewer(llm_client=llm_client)
    skill_reviewer = SkillReviewer(llm_client=llm_client)

    if args.list_sessions:
        print(format_sessions(store.list_sessions(limit=20)))
        return

    if args.inspect_session:
        try:
            print(format_session_inspection(store.inspect_session(args.inspect_session)))
        except SessionStoreError as exc:
            print(f"Session error: {exc}")
        return

    try:
        agent, session_id = create_agent(
            args,
            session_store=store,
            llm_client=llm_client,
            memory_reviewer=memory_reviewer,
            skill_reviewer=skill_reviewer,
        )
    except ConfigError as exc:
        print(f"Config error: {exc}")
        return
    except SessionStoreError as exc:
        print(f"Session error: {exc}")
        return

    print(f"lulu-agent started. model={agent.llm_client.model}")
    print(f"Session id: {session_id}")
    print("Type /exit or /quit to exit.")

    while True:
        try:
            user_input = read_user_input("\nlulu-agent> ").strip()
        except EOFError:
            print('[EOFError] bye')
            break
        except KeyboardInterrupt:
            print()
            break
        
        if not user_input:
            continue
        if user_input in {"/exit", "/quit"}:
            print("bye")
            break

        try:
            response = agent.run(user_input)
        except Exception as exc:
            print(f"[Main Error] {exc}")
            continue


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
