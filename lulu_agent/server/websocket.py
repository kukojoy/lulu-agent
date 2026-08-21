from __future__ import annotations

import asyncio
import queue
from typing import Any

from lulu_agent.config import ConfigError
from lulu_agent.server.events import (
    build_server_error_event,
    build_server_ready_event,
    publish_queue_message,
)
from lulu_agent.server.runner import ServerRunner, ServerRunnerError
from lulu_agent.storage.session_store import SessionStoreError

try:
    from fastapi import WebSocket, WebSocketDisconnect
except ImportError:  # pragma: no cover - server dependency guard
    WebSocket = Any  # type: ignore[assignment,misc]
    WebSocketDisconnect = Exception  # type: ignore[assignment,misc]


async def handle_session_events_socket(
    websocket: WebSocket,
    runner: ServerRunner,
    session_id: str,
) -> None:
    await websocket.accept()
    try:
        runner.resume_session(session_id)
    except SessionStoreError:
        await websocket.send_json(build_server_error_event(
            f"Session not found: {session_id}",
            "session_not_found",
        ))
        await websocket.close(code=1008)
        return

    subscriber = runner.subscribe_events(session_id)
    await websocket.send_json(build_server_ready_event(session_id, runner.get_runtime_state(session_id)))
    try:
        await _send_subscribed_events(websocket, subscriber)
    except WebSocketDisconnect:
        pass
    finally:
        runner.unsubscribe_events(session_id, subscriber)


async def handle_session_run_socket(
    websocket: WebSocket,
    runner: ServerRunner,
    session_id: str,
) -> None:
    await websocket.accept()
    try:
        runner.resume_session(session_id)
    except SessionStoreError:
        await websocket.send_json(build_server_error_event(
            f"Session not found: {session_id}",
            "session_not_found",
        ))
        await websocket.close(code=1008)
        return

    subscriber = runner.subscribe_events(session_id)
    await websocket.send_json(build_server_ready_event(session_id, runner.get_runtime_state(session_id)))

    run_tasks: set[asyncio.Task] = set()
    send_task = asyncio.create_task(_send_subscribed_events(websocket, subscriber))
    receive_task = asyncio.create_task(
        _receive_run_commands(websocket, runner, session_id, subscriber, run_tasks)
    )
    try:
        done, pending = await asyncio.wait(
            {send_task, receive_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in done:
            task.result()
        for task in pending:
            task.cancel()
    except WebSocketDisconnect:
        pass
    finally:
        send_task.cancel()
        receive_task.cancel()
        for task in run_tasks:
            task.cancel()
        runner.unsubscribe_events(session_id, subscriber)


async def _send_subscribed_events(
    websocket: WebSocket,
    subscriber: queue.Queue[dict[str, Any]],
) -> None:
    while True:
        try:
            event = await asyncio.to_thread(subscriber.get, True, 1.0)
        except queue.Empty:
            continue
        await websocket.send_json(event)


async def _receive_run_commands(
    websocket: WebSocket,
    runner: ServerRunner,
    session_id: str,
    subscriber: queue.Queue[dict[str, Any]],
    run_tasks: set[asyncio.Task],
) -> None:
    while True:
        command = await websocket.receive_json()
        if command.get("type") == "approval_response":
            _handle_approval_response(command, runner, session_id, subscriber)
            continue

        if command.get("type") == "interrupt":
            _handle_interrupt(runner, session_id, subscriber)
            continue

        if command.get("type") != "user_message":
            _publish_error(
                subscriber,
                "Unsupported command type.",
                "invalid_command",
                runner.get_runtime_state(session_id),
            )
            continue

        task = asyncio.create_task(
            _run_user_message(runner, session_id, command.get("content"), subscriber)
        )
        run_tasks.add(task)
        task.add_done_callback(run_tasks.discard)


async def _run_user_message(
    runner: ServerRunner,
    session_id: str,
    content: Any,
    subscriber: queue.Queue[dict[str, Any]],
) -> None:
    try:
        await asyncio.to_thread(runner.run_message, session_id, content)
    except (ValueError, SessionStoreError, ConfigError) as exc:
        code = "server_error"
        if isinstance(exc, ValueError):
            code = "invalid_message"
        elif isinstance(exc, SessionStoreError):
            code = "session_not_found"
        elif isinstance(exc, ConfigError):
            code = "config_error"
        runtime = None if isinstance(exc, SessionStoreError) else runner.get_runtime_state(session_id)
        _publish_error(subscriber, str(exc), code, runtime)
    except ServerRunnerError as exc:
        _publish_error(subscriber, str(exc), exc.code, runner.get_runtime_state(session_id))
    except Exception as exc:
        _publish_error(subscriber, str(exc), "unexpected_error", runner.get_runtime_state(session_id))


def _handle_approval_response(
    command: dict[str, Any],
    runner: ServerRunner,
    session_id: str,
    subscriber: queue.Queue[dict[str, Any]],
) -> None:
    request_id = str(command.get("request_id") or "")
    approved = bool(command.get("approved"))
    if request_id and runner.resolve_approval(session_id, request_id, approved):
        return
    _publish_error(
        subscriber,
        "Approval request not found.",
        "approval_not_found",
        runner.get_runtime_state(session_id),
    )


def _handle_interrupt(
    runner: ServerRunner,
    session_id: str,
    subscriber: queue.Queue[dict[str, Any]],
) -> None:
    if runner.interrupt_session(session_id):
        return
    _publish_error(
        subscriber,
        "No running turn to interrupt.",
        "interrupt_unavailable",
        runner.get_runtime_state(session_id),
    )


def _publish_error(
    subscriber: queue.Queue[dict[str, Any]],
    message: str,
    code: str,
    runtime: dict[str, Any] | None = None,
) -> None:
    publish_queue_message(subscriber, build_server_error_event(message, code, runtime))
