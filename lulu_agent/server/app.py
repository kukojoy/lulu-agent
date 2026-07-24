from __future__ import annotations

import asyncio
import queue
from typing import Any

from lulu_agent.config import ConfigError
from lulu_agent.server.runner import ServerRunner
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


def create_app(runner: ServerRunner | None = None):
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
    runner = runner or ServerRunner()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/sessions")
    def list_sessions(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        return {"sessions": runner.list_sessions(limit=limit)}

    @app.post("/sessions")
    def create_session() -> dict[str, Any]:
        return {"session": runner.create_session()}

    @app.delete("/sessions/{session_id}")
    def delete_session(session_id: str) -> dict[str, Any]:
        try:
            metadata = runner.delete_session(session_id)
        except SessionStoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"deleted": True, "session": metadata}

    @app.get("/sessions/{session_id}")
    def inspect_session(session_id: str) -> dict[str, Any]:
        try:
            return runner.inspect_session(session_id)
        except SessionStoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/sessions/{session_id}/messages")
    def load_messages(session_id: str) -> dict[str, Any]:
        try:
            return {"messages": runner.load_messages(session_id)}
        except SessionStoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/sessions/{session_id}/context")
    def inspect_context(session_id: str) -> dict[str, Any]:
        try:
            return runner.inspect_context(session_id)
        except SessionStoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/sessions/{session_id}/task")
    def get_task_state(session_id: str) -> dict[str, Any]:
        try:
            return {"task_state": runner.get_task_state(session_id)}
        except SessionStoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/sessions/{session_id}/trace")
    def get_trace(session_id: str, turn_id: str | None = None) -> dict[str, Any]:
        try:
            return {"timeline": runner.get_trace_timeline(session_id, turn_id=turn_id)}
        except (SessionStoreError, TraceStoreError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/sessions/{session_id}/messages")
    async def send_message(session_id: str, request: MessageRequest) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(runner.run_message, session_id, request.content)
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
            runner.resume_session(session_id)
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
        subscriber = runner.subscribe_events(session_id)
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
            runner.unsubscribe_events(session_id, subscriber)

    @app.websocket("/sessions/{session_id}/run")
    async def session_run(websocket: WebSocket, session_id: str) -> None:
        await websocket.accept()
        try:
            runner.resume_session(session_id)
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

        subscriber = runner.subscribe_events(session_id)
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
                    await asyncio.to_thread(runner.run_message, session_id, content)
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
            runner.unsubscribe_events(session_id, subscriber)

    return app


app = create_app()
