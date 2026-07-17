"""任务状态工具

用于读取或更新当前会话的任务状态, 适用于长时程, 多步骤工作

Actions:
    - read: 读取当前任务状态
    - update: 更新当前任务状态, overwrite 选择覆盖完整状态/增量更新状态
"""

from lulu_agent.runtime.task_state import TaskState
from lulu_agent.storage.session_store import SessionStore
from lulu_agent.tools import ToolResult, tool


@tool(
    name="task_state",
    description=(
        "Read or update the current session task state for multi-step work. "
        "Read before answering progress or next-step questions. Update after the "
        "user changes goal/scope/constraints, after completing or blocking a step, "
        "and after creating important outputs, so goal, steps, blockers, verified "
        "results, and next_action stay current. Set overwrite=true to write a full "
        "new state. Set overwrite=false to read current state, update top-level "
        "fields, and replace or append steps by step id. This is temporary progress, "
        "not memory."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "Use read to inspect progress or update to write task state.",
                "enum": ["read", "update"],
            },
            "overwrite": {
                "type": "boolean",
                "description": "Required for update. overwrite=true writes state as the full new task state. overwrite=false reads current state, updates provided top-level fields, and replaces or appends provided steps by id.",
            },
            "state": {
                "type": "object",
                "description": "Task state object. Required for update. Full object when overwrite=true; partial object allowed when overwrite=false.",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": "Current task goal.",
                    },
                    "status": {
                        "type": "string",
                        "description": "Current task status.",
                        "enum": ["active", "completed", "blocked", "cancelled"],
                    },
                    "steps": {
                        "type": "array",
                        "description": "Task steps in id order. Keep ids stable and unique. At most one step may be in_progress.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {
                                    "type": "integer",
                                    "description": "Stable positive step number.",
                                    "minimum": 1,
                                },
                                "step": {
                                    "type": "string",
                                    "description": "Concrete step description.",
                                },
                                "status": {
                                    "type": "string",
                                    "description": "Step status.",
                                    "enum": [
                                        "pending",
                                        "in_progress",
                                        "completed",
                                        "blocked",
                                        "cancelled",
                                    ],
                                },
                            },
                            "required": ["id", "step", "status"],
                        },
                    },
                    "blockers": {
                        "type": "array",
                        "description": "Current blockers.",
                        "items": {"type": "string"},
                    },
                    "verified": {
                        "type": "array",
                        "description": "Verified facts or checks.",
                        "items": {"type": "string"},
                    },
                    "next_action": {
                        "type": "string",
                        "description": "Recommended next action.",
                    },
                },
            },
        },
        "required": ["action"],
    },
)
def task_state(args):
    session_store = args.get("_session_store")
    session_id = args.get("_session_id")
    if not isinstance(session_store, SessionStore) or not session_id:
        return ToolResult(ok=False, error="task_state requires an active session.")

    action = args["action"]
    if action == "read":
        current = session_store.load_latest_task_state(session_id)
        return ToolResult(ok=True, output={"task_state": current.to_dict() if current else None})

    if action == "update":
        overwrite = args.get("overwrite")
        if not isinstance(overwrite, bool):
            return ToolResult(ok=False, error="overwrite must be a boolean for update.")
        state = args.get("state")
        if not isinstance(state, dict):
            return ToolResult(ok=False, error="state must be an object for update.")
        try:
            if overwrite:
                current = TaskState.from_dict(state)
            else:
                current = _merge_task_state(session_store.load_latest_task_state(session_id), state)
        except ValueError as exc:
            return ToolResult(ok=False, error=str(exc))
        session_store.append_task_state(session_id, current)
        return ToolResult(ok=True, output={"task_state": current.to_dict()})

    return ToolResult(ok=False, error="Unknown task_state action. Use one of: read, update.")


def _merge_task_state(current: TaskState | None, patch: dict) -> TaskState:
    if current is None:
        raise ValueError("task state merge requires an existing task state.")

    data = current.to_dict()
    for key in ("goal", "status", "blockers", "verified", "next_action"):
        if key in patch:
            data[key] = patch[key]

    if "steps" in patch:
        steps = patch["steps"]
        if not isinstance(steps, list):
            raise ValueError("task steps must be a list.")
        merged_steps = list(data["steps"])
        index_by_id = {step["id"]: index for index, step in enumerate(merged_steps)}
        for step in steps:
            if not isinstance(step, dict):
                raise ValueError("task step must be an object.")
            step_id = step.get("id")
            if step_id in index_by_id:
                merged_steps[index_by_id[step_id]] = step
            else:
                merged_steps.append(step)
        data["steps"] = merged_steps

    return TaskState.from_dict(data)
