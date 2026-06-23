import argparse
from pathlib import Path

from lulu_agent.agent_loop import AgentLoop
from lulu_agent.cli_input import read_user_input, setup_line_editing
from lulu_agent.config import ConfigError
from lulu_agent.llm_client import LLMClientError
from lulu_agent.session_store import SessionStore, SessionStoreError


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
) -> tuple[AgentLoop, str]:
    store = session_store or SessionStore()
    if args.resume:
        session_id = args.resume
        store.validate_session(session_id)
    else:
        metadata = store.create_session(cwd=Path.cwd())
        session_id = metadata["session_id"]

    return AgentLoop(session_store=store, session_id=session_id), session_id


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
        "Transcript summary:",
    ]
    for index, message in enumerate(summary["messages"], start=1):
        detail = message.get("content") or ""
        if message.get("has_tool_calls"):
            detail = f"{detail} [tool_calls]".strip()
        if message.get("tool_call_id"):
            detail = f"{detail} [tool_call_id={message['tool_call_id']}]".strip()
        lines.append(f"{index}. {message.get('role')}: {detail}")
    return "\n".join(lines)


def main(argv: list[str] | None = None):
    setup_line_editing()
    args = parse_args(argv)
    store = SessionStore()

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
        agent, session_id = create_agent(args, session_store=store)
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
            print('[user query:]', user_input)
        except EOFError:
            print('[EOFError] bye')
            break
        
        if not user_input:
            continue
        if user_input in {"/exit", "/quit"}:
            print("bye")
            break

        try:
            response = agent.run(user_input)
        except LLMClientError as exc:
            print(f"LLM error: {exc}")
            continue
        print('[agent response:]', response)


if __name__ == "__main__":
    main()
