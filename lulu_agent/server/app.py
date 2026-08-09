from __future__ import annotations

import asyncio
import queue
from typing import Any

from lulu_agent.config import ConfigError
from lulu_agent.server.runner import ServerRunner, ServerRunnerError
from lulu_agent.skills.store import SkillStoreError
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


class ModelSwitchRequest(BaseModel):
    provider: str
    model: str


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

    @app.get("/sessions/{session_id}/runtime")
    def get_runtime_state(session_id: str) -> dict[str, Any]:
        try:
            return {"runtime": runner.get_runtime_state(session_id)}
        except SessionStoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/runtime/model")
    def get_model_config() -> dict[str, Any]:
        try:
            return {"model_config": runner.get_model_config()}
        except ConfigError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/sessions/{session_id}/model")
    def get_session_model_config(session_id: str) -> dict[str, Any]:
        try:
            return {"model_config": runner.get_session_model_config(session_id)}
        except SessionStoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ConfigError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/runtime/model/providers")
    def list_model_providers() -> dict[str, Any]:
        try:
            return {"providers": runner.list_model_providers()}
        except ConfigError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/runtime/model/providers/{provider}/models")
    def list_provider_models(provider: str) -> dict[str, Any]:
        try:
            return runner.list_provider_models(provider)
        except ConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/sessions/{session_id}/model")
    def update_session_model(session_id: str, request: ModelSwitchRequest) -> dict[str, Any]:
        try:
            return {"model_config": runner.update_session_model(session_id, request.provider, request.model)}
        except SessionStoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ServerRunnerError as exc:
            raise HTTPException(status_code=409, detail={"message": str(exc), "code": exc.code}) from exc
        except ConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/sessions/{session_id}/mcp-tools")
    def list_mcp_tools(session_id: str) -> dict[str, Any]:
        try:
            return runner.list_mcp_tools(session_id)
        except SessionStoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/sessions/{session_id}/mcp/reload")
    def reload_mcp_tools(session_id: str) -> dict[str, Any]:
        try:
            return runner.reload_mcp_tools(session_id)
        except SessionStoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ServerRunnerError as exc:
            raise HTTPException(status_code=409, detail={"message": str(exc), "code": exc.code}) from exc

    @app.get("/memory")
    def get_memory() -> dict[str, Any]:
        return {"memory": runner.get_memory()}

    @app.get("/skills")
    def list_skills() -> dict[str, Any]:
        return runner.list_skills()

    @app.get("/skills/{name}")
    def read_skill(name: str) -> dict[str, Any]:
        try:
            return {"skill": runner.read_skill(name)}
        except SkillStoreError as exc:
            raise HTTPException(status_code=404, detail=exc.error_message) from exc

    @app.post("/sessions/{session_id}/messages")
    async def send_message(session_id: str, request: MessageRequest) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(runner.run_message, session_id, request.content)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ServerRunnerError as exc:
            raise HTTPException(status_code=409, detail={"message": str(exc), "code": exc.code}) from exc
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
                    "payload": {
                        "message": f"Session not found: {session_id}",
                        "code": "session_not_found",
                    },
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
                "payload": {
                    "session_id": session_id,
                    "runtime": runner.get_runtime_state(session_id),
                },
            }
        )
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
                    "payload": {
                        "message": f"Session not found: {session_id}",
                        "code": "session_not_found",
                    },
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
                "payload": {
                    "session_id": session_id,
                    "runtime": runner.get_runtime_state(session_id),
                },
            }
        )

        def publish_server_message(message: dict[str, Any]) -> None:
            try:
                subscriber.put_nowait(message)
            except queue.Full:
                pass

        def server_error_payload(message: str, code: str, runtime: dict[str, Any] | None = None) -> dict[str, Any]:
            payload: dict[str, Any] = {"message": message, "code": code}
            if runtime is not None:
                payload["runtime"] = runtime
            return {
                "type": "server_error",
                "turn_id": "",
                "timestamp": "",
                "payload": payload,
            }

        async def send_events() -> None:
            while True:
                try:
                    event = await asyncio.to_thread(subscriber.get, True, 1.0)
                except queue.Empty:
                    continue
                await websocket.send_json(event)

        run_tasks: set[asyncio.Task] = set()

        async def run_user_message(content: Any) -> None:
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
                publish_server_message(server_error_payload(str(exc), code, runtime))
            except ServerRunnerError as exc:
                publish_server_message(
                    server_error_payload(str(exc), exc.code, runner.get_runtime_state(session_id))
                )
            except Exception as exc:
                publish_server_message(
                    server_error_payload(str(exc), "unexpected_error", runner.get_runtime_state(session_id))
                )

        async def receive_commands() -> None:
            while True:
                command = await websocket.receive_json()
                if command.get("type") == "approval_response":
                    request_id = str(command.get("request_id") or "")
                    approved = bool(command.get("approved"))
                    if not request_id or not runner.resolve_approval(session_id, request_id, approved):
                        publish_server_message(
                            server_error_payload(
                                "Approval request not found.",
                                "approval_not_found",
                                runner.get_runtime_state(session_id),
                            )
                        )
                    continue

                if command.get("type") == "interrupt":
                    if not runner.interrupt_session(session_id):
                        publish_server_message(
                            server_error_payload(
                                "No running turn to interrupt.",
                                "interrupt_unavailable",
                                runner.get_runtime_state(session_id),
                            )
                        )
                    continue

                if command.get("type") != "user_message":
                    publish_server_message(
                        server_error_payload(
                            "Unsupported command type.",
                            "invalid_command",
                            runner.get_runtime_state(session_id),
                        )
                    )
                    continue
                content = command.get("content")
                task = asyncio.create_task(run_user_message(content))
                run_tasks.add(task)
                task.add_done_callback(run_tasks.discard)

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
            for task in run_tasks:
                task.cancel()
            runner.unsubscribe_events(session_id, subscriber)

    return app


app = create_app()
