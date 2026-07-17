from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

TaskStatus = Literal["active", "completed", "blocked", "cancelled"]
TaskStepStatus = Literal["pending", "in_progress", "completed", "blocked", "cancelled"]

TASK_STATUSES = {"active", "completed", "blocked", "cancelled"}
TASK_STEP_STATUSES = {"pending", "in_progress", "completed", "blocked", "cancelled"}


@dataclass(frozen=True)
class TaskStep:
    """单个任务步骤, 用于记录会话任务步骤细节, 字段包括步骤id, 步骤描述, 步骤状态"""
    id: int
    step: str
    status: TaskStepStatus

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskStep":
        step_id = data.get("id")
        step = data.get("step")
        status = data.get("status")
        if not isinstance(step_id, int) or isinstance(step_id, bool) or step_id < 1:
            raise ValueError("task step id must be a positive integer.")
        if not isinstance(step, str) or not step.strip():
            raise ValueError("task step must be a non-empty string.")
        if status not in TASK_STEP_STATUSES:
            raise ValueError("task step status is invalid.")
        return cls(id=step_id, step=step.strip(), status=status)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "step": self.step,
            "status": self.status,
        }


@dataclass(frozen=True)
class TaskState:
    """任务状态, 用于记录当前会话的任务目标, 任务状态, 步骤细节, 阻塞信息, 验证信息, 下一步行动建议等"""
    goal: str
    status: TaskStatus
    steps: list[TaskStep] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    verified: list[str] = field(default_factory=list)
    next_action: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskState":
        goal = data.get("goal")
        status = data.get("status")
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("task goal must be a non-empty string.")
        if status not in TASK_STATUSES:
            raise ValueError("task status is invalid.")

        steps = data.get("steps", [])
        blockers = data.get("blockers", [])
        verified = data.get("verified", [])
        next_action = data.get("next_action", "")
        if not isinstance(steps, list):
            raise ValueError("task steps must be a list.")
        if not isinstance(blockers, list) or not all(isinstance(item, str) for item in blockers):
            raise ValueError("task blockers must be a list of strings.")
        if not isinstance(verified, list) or not all(isinstance(item, str) for item in verified):
            raise ValueError("task verified must be a list of strings.")
        if not isinstance(next_action, str):
            raise ValueError("task next_action must be a string.")

        parsed_steps = []
        for item in steps:
            if not isinstance(item, dict):
                raise ValueError("task step must be an object.")
            parsed_steps.append(TaskStep.from_dict(item))
        step_ids = [step.id for step in parsed_steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("task step ids must be unique.")
        in_progress = [step for step in parsed_steps if step.status == "in_progress"]
        if len(in_progress) > 1:
            raise ValueError("task state can have at most one in_progress step.")

        return cls(
            goal=goal.strip(),
            status=status,
            steps=parsed_steps,
            blockers=[item.strip() for item in blockers if item.strip()],
            verified=[item.strip() for item in verified if item.strip()],
            next_action=next_action.strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "status": self.status,
            "steps": [step.to_dict() for step in self.steps],
            "blockers": list(self.blockers),
            "verified": list(self.verified),
            "next_action": self.next_action,
        }

    def should_inject(self) -> bool:
        return self.status in {"active", "blocked"} and bool(self.goal or self.steps or self.next_action)
