from __future__ import annotations

import asyncio
from typing import Any

from lulu_agent.config import ConfigError
from lulu_agent.server.http_errors import (
    bad_request_error,
    conflict_error,
    internal_error,
    not_found_error,
    session_error,
    skill_not_found_error,
)
from lulu_agent.server.runner import ServerRunner, ServerRunnerError
from lulu_agent.server.websocket import handle_session_events_socket, handle_session_run_socket
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


class CreateSessionRequest(BaseModel):
    workspace: str | None = None


class DirectoryBrowseRequest(BaseModel):
    path: str | None = None


class ModelSwitchRequest(BaseModel):
    provider: str
    model: str


def create_app(runner: ServerRunner | None = None):
    try:
        from fastapi import FastAPI, Query
        from fastapi.middleware.cors import CORSMiddleware
    except ImportError as exc:
        raise RuntimeError(
            "FastAPI server dependencies are missing. Install fastapi to run lulu_agent.server."
        ) from exc

    app = FastAPI(title="lulu-agent", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https?://(127\.0\.0\.1|localhost):\d+$",
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
    def create_session(request: CreateSessionRequest | None = None) -> dict[str, Any]:
        try:
            return {"session": runner.create_session(workspace=request.workspace if request else None)}
        except SessionStoreError as exc:
            raise session_error(exc) from exc

    @app.post("/runtime/workspace/browse")
    def browse_workspace(request: DirectoryBrowseRequest | None = None) -> dict[str, Any]:
        try:
            return runner.browse_workspace(request.path if request else None)
        except SessionStoreError as exc:
            raise session_error(exc) from exc

    @app.delete("/sessions/{session_id}")
    def delete_session(session_id: str) -> dict[str, Any]:
        try:
            metadata = runner.delete_session(session_id)
        except ServerRunnerError as exc:
            raise conflict_error(exc) from exc
        except SessionStoreError as exc:
            raise session_error(exc) from exc
        return {"deleted": True, "session": metadata}

    @app.get("/sessions/{session_id}")
    def inspect_session(session_id: str) -> dict[str, Any]:
        try:
            return runner.inspect_session(session_id)
        except SessionStoreError as exc:
            raise session_error(exc) from exc

    @app.get("/sessions/{session_id}/messages")
    def load_messages(session_id: str) -> dict[str, Any]:
        try:
            return {"messages": runner.load_messages(session_id)}
        except SessionStoreError as exc:
            raise session_error(exc) from exc

    @app.get("/sessions/{session_id}/context")
    def inspect_context(session_id: str) -> dict[str, Any]:
        try:
            return runner.inspect_context(session_id)
        except SessionStoreError as exc:
            raise session_error(exc) from exc

    @app.get("/sessions/{session_id}/task")
    def get_task_state(session_id: str) -> dict[str, Any]:
        try:
            return {"task_state": runner.get_task_state(session_id)}
        except SessionStoreError as exc:
            raise session_error(exc) from exc

    @app.get("/sessions/{session_id}/trace")
    def get_trace(session_id: str, turn_id: str | None = None) -> dict[str, Any]:
        try:
            return {"timeline": runner.get_trace_timeline(session_id, turn_id=turn_id)}
        except (SessionStoreError, TraceStoreError) as exc:
            raise session_error(exc) from exc

    @app.get("/sessions/{session_id}/trace/turns")
    def get_trace_turns(session_id: str) -> dict[str, Any]:
        try:
            return {"turns": runner.get_trace_turns(session_id)}
        except (SessionStoreError, TraceStoreError) as exc:
            raise session_error(exc) from exc

    @app.get("/sessions/{session_id}/runtime")
    def get_runtime_state(session_id: str) -> dict[str, Any]:
        try:
            return {"runtime": runner.get_runtime_state(session_id)}
        except SessionStoreError as exc:
            raise session_error(exc) from exc

    @app.get("/runtime/model")
    def get_model_config() -> dict[str, Any]:
        try:
            return {"model_config": runner.get_model_config()}
        except ConfigError as exc:
            raise internal_error(exc) from exc

    @app.get("/sessions/{session_id}/model")
    def get_session_model_config(session_id: str) -> dict[str, Any]:
        try:
            return {"model_config": runner.get_session_model_config(session_id)}
        except SessionStoreError as exc:
            raise session_error(exc) from exc
        except ConfigError as exc:
            raise internal_error(exc) from exc

    @app.get("/runtime/model/providers")
    def list_model_providers() -> dict[str, Any]:
        try:
            return {"providers": runner.list_model_providers()}
        except ConfigError as exc:
            raise internal_error(exc) from exc

    @app.get("/runtime/model/providers/{provider}/models")
    def list_provider_models(provider: str) -> dict[str, Any]:
        try:
            return runner.list_provider_models(provider)
        except ConfigError as exc:
            raise bad_request_error(exc) from exc

    @app.post("/sessions/{session_id}/model")
    def update_session_model(session_id: str, request: ModelSwitchRequest) -> dict[str, Any]:
        try:
            return {"model_config": runner.update_session_model(session_id, request.provider, request.model)}
        except SessionStoreError as exc:
            raise session_error(exc) from exc
        except ServerRunnerError as exc:
            raise conflict_error(exc) from exc
        except ConfigError as exc:
            raise bad_request_error(exc) from exc

    @app.get("/sessions/{session_id}/mcp-tools")
    def list_mcp_tools(session_id: str) -> dict[str, Any]:
        try:
            return runner.list_mcp_tools(session_id)
        except SessionStoreError as exc:
            raise session_error(exc) from exc

    @app.post("/sessions/{session_id}/mcp/reload")
    def reload_mcp_tools(session_id: str) -> dict[str, Any]:
        try:
            return runner.reload_mcp_tools(session_id)
        except SessionStoreError as exc:
            raise session_error(exc) from exc
        except ServerRunnerError as exc:
            raise conflict_error(exc) from exc

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
            raise skill_not_found_error(exc) from exc

    @app.post("/sessions/{session_id}/messages")
    async def send_message(session_id: str, request: MessageRequest) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(runner.run_message, session_id, request.content)
        except ValueError as exc:
            raise bad_request_error(exc) from exc
        except ServerRunnerError as exc:
            raise conflict_error(exc) from exc
        except SessionStoreError as exc:
            raise session_error(exc) from exc
        except ConfigError as exc:
            raise internal_error(exc) from exc

    @app.websocket("/sessions/{session_id}/events")
    async def session_events(websocket: WebSocket, session_id: str) -> None:
        await handle_session_events_socket(websocket, runner, session_id)

    @app.websocket("/sessions/{session_id}/run")
    async def session_run(websocket: WebSocket, session_id: str) -> None:
        await handle_session_run_socket(websocket, runner, session_id)

    return app


app = create_app()
