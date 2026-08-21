from __future__ import annotations

import queue
import threading

from lulu_agent.runtime.events import EVENT_APPROVAL_REQUEST, EventPayloadBuilder, RuntimeEvent
from lulu_agent.safety.approval import ApprovalProvider, ApprovalRequest
from lulu_agent.server.events import EventHub


class ServerApprovalProvider(ApprovalProvider):
    def __init__(self, event_hub: EventHub, session_id: str, timeout_seconds: int = 300):
        self.event_hub = event_hub
        self.session_id = session_id
        self.timeout_seconds = timeout_seconds
        self._lock = threading.Lock()
        self._pending: dict[str, queue.Queue[bool]] = {}
        self._requests: dict[str, ApprovalRequest] = {}

    def request_approval(self, request: ApprovalRequest) -> bool:
        response_queue: queue.Queue[bool] = queue.Queue(maxsize=1)
        with self._lock:
            self._pending[request.request_id] = response_queue
            self._requests[request.request_id] = request

        self.event_hub.publish(
            self.session_id,
            RuntimeEvent(
                type=EVENT_APPROVAL_REQUEST,
                turn_id="",
                payload=EventPayloadBuilder.build_approval_request_payload(
                    request_id=request.request_id,
                    category=request.category,
                    reason=request.reason,
                    subject=request.subject,
                ),
            ),
        )

        try:
            return response_queue.get(timeout=self.timeout_seconds)
        except queue.Empty:
            return False
        finally:
            with self._lock:
                self._pending.pop(request.request_id, None)
                self._requests.pop(request.request_id, None)

    def resolve(self, request_id: str, approved: bool) -> bool:
        with self._lock:
            response_queue = self._pending.get(request_id)
        if response_queue is None:
            return False
        try:
            response_queue.put_nowait(bool(approved))
        except queue.Full:
            return False
        return True

    def cancel_pending(self) -> int:
        with self._lock:
            queues = list(self._pending.values())
        cancelled = 0
        for response_queue in queues:
            try:
                response_queue.put_nowait(False)
                cancelled += 1
            except queue.Full:
                continue
        return cancelled

    def pending_request(self) -> dict[str, str] | None:
        with self._lock:
            request = next(iter(self._requests.values()), None)
        if request is None:
            return None
        return {
            "request_id": request.request_id,
            "category": request.category,
            "reason": request.reason,
            "subject": request.subject,
        }
