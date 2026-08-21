from __future__ import annotations

from lulu_agent.core.agent_loop import AgentLoop
from lulu_agent.llm.client import LLMClient
from lulu_agent.llm.response import LLMClientConfig
from lulu_agent.memory.store import MemoryStore
from lulu_agent.reviewers.memory import MemoryReviewer
from lulu_agent.reviewers.skills import SkillReviewer
from lulu_agent.runtime.event_sinks import CompositeEventSink, PersistentEventSink
from lulu_agent.server.events import EventHub, HubEventSink
from lulu_agent.skills.store import SkillStore
from lulu_agent.storage.session_store import SessionStore
from lulu_agent.storage.trace_store import TraceStore


def build_server_agent(
    *,
    session_store: SessionStore,
    trace_store: TraceStore,
    memory_store: MemoryStore,
    skill_store: SkillStore,
    event_hub: EventHub,
    session_id: str,
    model_config: LLMClientConfig,
) -> AgentLoop:
    return AgentLoop(
        session_store=session_store,
        session_id=session_id,
        llm_client=LLMClient(model_config),
        event_sink=CompositeEventSink(
            [
                HubEventSink(event_hub, session_id),
                PersistentEventSink(trace_store, session_id),
            ]
        ),
        reviewers=[
            MemoryReviewer(memory_store=memory_store),
            SkillReviewer(skill_store=skill_store),
        ],
    )
