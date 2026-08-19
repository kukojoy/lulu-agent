from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from lulu_agent.runtime.review import ReviewerType
from lulu_agent.runtime.message import Message
from lulu_agent.llm.client import LLMClient


@dataclass(frozen=True)
class BaseReviewResult:
    response: str
    summaries: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.summaries)

    @property
    def summary_content(self) -> str:
        if not self.summaries:
            return "no changes"
        shown = self.summaries[:3]
        summary = "; ".join(shown)
        remaining = len(self.summaries) - len(shown)
        if remaining > 0:
            summary = f"{summary}; and {remaining} more"
        return summary


class BaseReviewer(ABC):
    type: ReviewerType
    review_turns: int

    @abstractmethod
    def review(self, messages_snapshot: list[Message], llm_client: LLMClient) -> BaseReviewResult:
        raise NotImplementedError
