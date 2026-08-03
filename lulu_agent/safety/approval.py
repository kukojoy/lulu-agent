from __future__ import annotations

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

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


_approval_provider: contextvars.ContextVar[ApprovalProvider | None] = contextvars.ContextVar(
    "approval_provider",
    default=None,
)


def request_approval(decision: SafetyDecision, subject: str) -> bool:
    request = ApprovalRequest(
        request_id=f"approval-{uuid4().hex[:12]}",
        category=decision.category,
        reason=decision.reason,
        subject=subject,
    )
    provider = _approval_provider.get()
    if provider is None:
        return False
    return provider.request_approval(request)


@contextmanager
def use_approval_provider(provider: ApprovalProvider):
    token = _approval_provider.set(provider)
    try:
        yield
    finally:
        _approval_provider.reset(token)
