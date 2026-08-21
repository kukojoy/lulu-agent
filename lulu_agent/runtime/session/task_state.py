from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from lulu_agent.runtime.session.model import SessionRuntimeModel
from lulu_agent.storage.session_record import SessionRecordType


class TaskStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class TaskStepStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


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
        try:
            parsed_status = TaskStepStatus(status)
        except ValueError:
            raise ValueError("task step status is invalid.")
        return cls(id=step_id, step=step.strip(), status=parsed_status)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "step": self.step,
            "status": self.status.value,
        }


@dataclass(frozen=True)
class TaskState(SessionRuntimeModel):
    """任务状态, 用于记录当前会话的任务目标, 任务状态, 步骤细节, 阻塞信息, 验证信息, 下一步行动建议等"""
    type = SessionRecordType.TASK_STATE

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
        try:
            parsed_status = TaskStatus(status)
        except ValueError:
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
        in_progress = [step for step in parsed_steps if step.status == TaskStepStatus.IN_PROGRESS]
        if len(in_progress) > 1:
            raise ValueError("task state can have at most one in_progress step.")

        return cls(
            goal=goal.strip(),
            status=parsed_status,
            steps=parsed_steps,
            blockers=[item.strip() for item in blockers if item.strip()],
            verified=[item.strip() for item in verified if item.strip()],
            next_action=next_action.strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "status": self.status.value,
            "steps": [step.to_dict() for step in self.steps],
            "blockers": list(self.blockers),
            "verified": list(self.verified),
            "next_action": self.next_action,
        }

    def should_inject(self) -> bool:
        return self.status in {TaskStatus.ACTIVE, TaskStatus.BLOCKED} and bool(self.goal or self.steps or self.next_action)
