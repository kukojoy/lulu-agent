import argparse
from pathlib import Path

from lulu_agent.core.agent_loop import AgentLoop
from lulu_agent.interaction import SessionInteractionService
from lulu_agent.interaction.formatters import (
    format_context_inspection,
    format_session_inspection,
    format_sessions,
)
from cli.input import read_user_input, setup_line_editing
from cli.approval_provider import CliApprovalProvider
from lulu_agent.config import ConfigError
from lulu_agent.llm.client import LLMClient
from lulu_agent.llm.providers import build_model_config
from lulu_agent.runtime.event_sinks import CliEventSink, CompositeEventSink, PersistentEventSink
from lulu_agent.safety.approval import use_approval_provider
from lulu_agent.storage.session_store import SessionStore, SessionStoreError
from lulu_agent.storage.trace_store import TraceStore
from lulu_agent.reviewers.base import BaseReviewer
from lulu_agent.reviewers.memory import MemoryReviewer
from lulu_agent.reviewers.skills import SkillReviewer


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
    parser.add_argument(
        "--inspect-context",
        metavar="SESSION_ID",
        help="Inspect the API context composition for one session and exit.",
    )
    return parser.parse_args(argv)


def create_agent(
    args: argparse.Namespace,
    session_store: SessionStore | None = None,
    llm_client: LLMClient | None = None,
    reviewers: list[BaseReviewer] | None = None,
) -> tuple[AgentLoop, str]:
    store = session_store or SessionStore()
    session_service = SessionInteractionService(store)
    if args.resume:
        session_id = session_service.resume_session(args.resume)
    else:
        metadata = session_service.create_session(cwd=Path.cwd())
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
        reviewers=reviewers,
    ), session_id


def main(argv: list[str] | None = None):
    setup_line_editing()
    args = parse_args(argv)
    store = SessionStore()
    session_service = SessionInteractionService(store)

    if args.list_sessions:
        print(format_sessions(session_service.list_sessions(limit=20)))
        return

    if args.inspect_session:
        try:
            print(format_session_inspection(session_service.inspect_session(args.inspect_session)))
        except SessionStoreError as exc:
            print(f"Session error: {exc}")
        return

    if args.inspect_context:
        try:
            inspection = session_service.inspect_context(args.inspect_context)
            print(format_context_inspection(args.inspect_context, inspection))
        except SessionStoreError as exc:
            print(f"Session error: {exc}")
        return

    try:
        llm_client = LLMClient(build_model_config())
        reviewers: list[BaseReviewer] = [
            MemoryReviewer(),
            SkillReviewer(),
        ]
        agent, session_id = create_agent(
            args,
            session_store=store,
            llm_client=llm_client,
            reviewers=reviewers,
        )
    except ConfigError as exc:
        print(f"Config error: {exc}")
        return
    except SessionStoreError as exc:
        print(f"Session error: {exc}")
        return

    print(f"lulu-agent started. model={agent.llm_client.model}")
    print(f"Session id: {session_id}")
    registry = getattr(agent, "tool_registry", None)
    if registry is not None:
        for issue in registry.get_issues():
            print(f"[MCP warning] {issue.source}: {issue.issue_message}")
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
            with use_approval_provider(CliApprovalProvider()):
                response = agent.run(user_input)
        except Exception as exc:
            print(f"[Main Error] {exc}")
            continue


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
