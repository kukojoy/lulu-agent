from __future__ import annotations

import asyncio
import json
import queue
from typing import Any

from lulu_agent.config import ConfigError
from lulu_agent.server.session_manager import ServerSessionManager
from lulu_agent.storage.jsonl import parse_jsonl_record
from lulu_agent.storage.session_store import SessionStoreError
from lulu_agent.storage.trace_store import TraceStoreError

try:
    from fastapi import WebSocket
    from pydantic import BaseModel
except ImportError:  # pragma: no cover - server dependency guard
    BaseModel = object  # type: ignore[assignment,misc]
    WebSocket = Any  # type: ignore[assignment,misc]


class MessageRequest(BaseModel):
    content: str


def create_app(manager: ServerSessionManager | None = None):
    try:
        from fastapi import FastAPI, HTTPException, Query, WebSocketDisconnect
        from fastapi.middleware.cors import CORSMiddleware
    except ImportError as exc:
        raise RuntimeError(
            "FastAPI server dependencies are missing. Install fastapi to run lulu_agent.server."
        ) from exc

    app = FastAPI(title="lulu-agent", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    session_manager = manager or ServerSessionManager()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/sessions")
    def list_sessions(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        return {"sessions": session_manager.list_sessions(limit=limit)}

    @app.post("/sessions")
    def create_session() -> dict[str, Any]:
        return {"session": session_manager.create_session()}

    @app.delete("/sessions/{session_id}")
    def delete_session(session_id: str) -> dict[str, Any]:
        try:
            metadata = _delete_session_in_api_layer(session_manager, session_id)
        except SessionStoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"deleted": True, "session": metadata}

    @app.get("/sessions/{session_id}")
    def inspect_session(session_id: str) -> dict[str, Any]:
        try:
            return session_manager.inspect_session(session_id)
        except SessionStoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/sessions/{session_id}/messages")
    def load_messages(session_id: str) -> dict[str, Any]:
        try:
            return {"messages": session_manager.load_messages(session_id)}
        except SessionStoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/sessions/{session_id}/context")
    def inspect_context(session_id: str) -> dict[str, Any]:
        try:
            return session_manager.inspect_context(session_id)
        except SessionStoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/sessions/{session_id}/task")
    def get_task_state(session_id: str) -> dict[str, Any]:
        try:
            return {"task_state": session_manager.get_task_state(session_id)}
        except SessionStoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/sessions/{session_id}/trace")
    def get_trace(session_id: str, turn_id: str | None = None) -> dict[str, Any]:
        try:
            return {"timeline": session_manager.get_trace_timeline(session_id, turn_id=turn_id)}
        except (SessionStoreError, TraceStoreError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/sessions/{session_id}/messages")
    async def send_message(session_id: str, request: MessageRequest) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(session_manager.run_message, session_id, request.content)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except SessionStoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ConfigError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.websocket("/sessions/{session_id}/events")
    async def session_events(websocket: WebSocket, session_id: str) -> None:
        await websocket.accept()
        try:
            session_manager.session_service.resume_session(session_id)
        except SessionStoreError:
            await websocket.send_json(
                {
                    "type": "server_error",
                    "turn_id": "",
                    "timestamp": "",
                    "payload": {"message": f"Session not found: {session_id}"},
                }
            )
            await websocket.close(code=1008)
            return

        await websocket.send_json(
            {
                "type": "server_ready",
                "turn_id": "",
                "timestamp": "",
                "payload": {"session_id": session_id},
            }
        )
        subscriber = session_manager.event_hub.subscribe(session_id)
        try:
            while True:
                try:
                    event = await asyncio.to_thread(subscriber.get, True, 1.0)
                except queue.Empty:
                    continue
                await websocket.send_json(event)
        except WebSocketDisconnect:
            pass
        finally:
            session_manager.event_hub.unsubscribe(session_id, subscriber)

    @app.websocket("/sessions/{session_id}/run")
    async def session_run(websocket: WebSocket, session_id: str) -> None:
        await websocket.accept()
        try:
            session_manager.session_service.resume_session(session_id)
        except SessionStoreError:
            await websocket.send_json(
                {
                    "type": "server_error",
                    "turn_id": "",
                    "timestamp": "",
                    "payload": {"message": f"Session not found: {session_id}"},
                }
            )
            await websocket.close(code=1008)
            return

        subscriber = session_manager.event_hub.subscribe(session_id)
        await websocket.send_json(
            {
                "type": "server_ready",
                "turn_id": "",
                "timestamp": "",
                "payload": {"session_id": session_id},
            }
        )

        async def send_events() -> None:
            while True:
                try:
                    event = await asyncio.to_thread(subscriber.get, True, 1.0)
                except queue.Empty:
                    continue
                await websocket.send_json(event)

        async def receive_commands() -> None:
            while True:
                command = await websocket.receive_json()
                if command.get("type") != "user_message":
                    await websocket.send_json(
                        {
                            "type": "server_error",
                            "turn_id": "",
                            "timestamp": "",
                            "payload": {"message": "Unsupported command type."},
                        }
                    )
                    continue
                content = command.get("content")
                try:
                    await asyncio.to_thread(session_manager.run_message, session_id, content)
                except (ValueError, SessionStoreError, ConfigError) as exc:
                    await websocket.send_json(
                        {
                            "type": "server_error",
                            "turn_id": "",
                            "timestamp": "",
                            "payload": {"message": str(exc)},
                        }
                    )

        send_task = asyncio.create_task(send_events())
        receive_task = asyncio.create_task(receive_commands())
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
            session_manager.event_hub.unsubscribe(session_id, subscriber)

    return app


app = create_app()


def _delete_session_in_api_layer(
    session_manager: ServerSessionManager,
    session_id: str,
) -> dict[str, Any]:
    store = session_manager.session_store
    metadata = session_manager.inspect_session(session_id)["metadata"]
    path = store.root / f"{session_id}.jsonl"
    if not path.exists():
        raise SessionStoreError(f"Session not found: {session_id}")

    path.unlink()
    _rewrite_session_index_without_session(session_manager, session_id)
    with session_manager._lock:
        session_manager._agents.pop(session_id, None)
        session_manager._locks.pop(session_id, None)
    return metadata


def _rewrite_session_index_without_session(
    session_manager: ServerSessionManager,
    session_id: str,
) -> None:
    index_path = session_manager.session_store.index_path
    if not index_path.exists():
        return

    kept_lines: list[str] = []
    for line_number, line in enumerate(index_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        metadata = parse_jsonl_record(index_path, line_number, line)
        record_session_id = metadata.get("session_id")
        if not isinstance(record_session_id, str) or not record_session_id:
            raise SessionStoreError(
                f"Invalid session index record at {index_path}:{line_number}: "
                "session_id must be a non-empty string."
            )
        if record_session_id != session_id:
            kept_lines.append(json.dumps(metadata, ensure_ascii=False))

    content = "\n".join(kept_lines)
    if content:
        content += "\n"
    index_path.write_text(content, encoding="utf-8")
