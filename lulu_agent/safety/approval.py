from __future__ import annotations

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from lulu_agent.runtime.cli_input import read_user_input
from lulu_agent.safety import SafetyDecision


@dataclass(frozen=True)
class ApprovalRequest:
    request_id: str
    category: str
    reason: str
    subject: str

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "category": self.category,
            "reason": self.reason,
            "subject": self.subject,
        }


class ApprovalProvider(Protocol):
    def request_approval(self, request: ApprovalRequest) -> bool:
        pass


class CliApprovalProvider(ApprovalProvider):
    def request_approval(self, request: ApprovalRequest) -> bool:
        print()
        print("[approval required]")
        print(f"category: {request.category}")
        print(f"reason: {request.reason}")
        print(f"subject: {request.subject}")
        try:
            answer = read_user_input("Allow once? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt, OSError):
            return False
        return answer in {"y", "yes"}


_approval_provider: contextvars.ContextVar[ApprovalProvider] = contextvars.ContextVar(
    "approval_provider",
    default=CliApprovalProvider(),
)

def request_approval(decision: SafetyDecision, subject: str) -> bool:
    request = ApprovalRequest(
        request_id=f"approval-{uuid4().hex[:12]}",
        category=decision.category,
        reason=decision.reason,
        subject=subject,
    )
    return _approval_provider.get().request_approval(request)

@contextmanager
def use_approval_provider(provider: ApprovalProvider):
    token = _approval_provider.set(provider)
    try:
        yield
    finally:
        _approval_provider.reset(token)
