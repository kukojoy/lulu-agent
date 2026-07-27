import type {
  MemoryView,
  RuntimeEvent,
  RuntimeState,
  SkillDocument,
  SkillListView,
  SessionInspection,
  SessionSummary,
  TaskState,
  TranscriptMessage,
  TraceTimelineItem,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";
const WS_BASE =
  import.meta.env.VITE_WS_BASE ??
  API_BASE.replace(/^http:/, "ws:").replace(/^https:/, "wss:");

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function listSessions(): Promise<SessionSummary[]> {
  const data = await requestJson<{ sessions: SessionSummary[] }>("/sessions");
  return data.sessions;
}

export async function createSession(): Promise<SessionSummary> {
  const data = await requestJson<{ session: SessionSummary }>("/sessions", {
    method: "POST",
  });
  return data.session;
}

export async function deleteSession(sessionId: string): Promise<SessionSummary> {
  const data = await requestJson<{ deleted: boolean; session: SessionSummary }>(
    `/sessions/${sessionId}`,
    {
      method: "DELETE",
    },
  );
  return data.session;
}

export function inspectSession(sessionId: string): Promise<SessionInspection> {
  return requestJson<SessionInspection>(`/sessions/${sessionId}`);
}

export async function loadMessages(sessionId: string): Promise<TranscriptMessage[]> {
  const data = await requestJson<{ messages: TranscriptMessage[] }>(
    `/sessions/${sessionId}/messages`,
  );
  return data.messages;
}

export async function getTaskState(sessionId: string): Promise<TaskState | null> {
  const data = await requestJson<{ task_state: TaskState | null }>(
    `/sessions/${sessionId}/task`,
  );
  return data.task_state;
}

export async function getRuntimeState(sessionId: string): Promise<RuntimeState> {
  const data = await requestJson<{ runtime: RuntimeState }>(
    `/sessions/${sessionId}/runtime`,
  );
  return data.runtime;
}

export async function getMemory(): Promise<MemoryView> {
  const data = await requestJson<{ memory: MemoryView }>("/memory");
  return data.memory;
}

export async function listSkills(): Promise<SkillListView> {
  return requestJson<SkillListView>("/skills");
}

export async function readSkill(name: string): Promise<SkillDocument> {
  const data = await requestJson<{ skill: SkillDocument }>(`/skills/${encodeURIComponent(name)}`);
  return data.skill;
}

export async function getTraceTimeline(sessionId: string): Promise<TraceTimelineItem[]> {
  const data = await requestJson<{ timeline: TraceTimelineItem[] }>(
    `/sessions/${sessionId}/trace`,
  );
  return data.timeline;
}

export function openEventSocket(
  sessionId: string,
  onEvent: (event: RuntimeEvent) => void,
): WebSocket {
  const socket = new WebSocket(`${WS_BASE}/sessions/${sessionId}/events`);
  socket.onmessage = (message) => {
    onEvent(JSON.parse(message.data) as RuntimeEvent);
  };
  return socket;
}

export function openRunSocket(
  sessionId: string,
  onEvent: (event: RuntimeEvent) => void,
): WebSocket {
  const socket = new WebSocket(`${WS_BASE}/sessions/${sessionId}/run`);
  socket.onmessage = (message) => {
    onEvent(JSON.parse(message.data) as RuntimeEvent);
  };
  return socket;
}
