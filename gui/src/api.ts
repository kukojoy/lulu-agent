import type {
  DirectoryBrowseView,
  MemoryView,
  McpReloadView,
  McpToolsView,
  ModelConfigView,
  ModelProviderView,
  ProviderModelsView,
  RuntimeEvent,
  RuntimeState,
  SkillDocument,
  SkillListView,
  SessionInspection,
  SessionSummary,
  TaskState,
  TranscriptMessage,
  TraceTimelineItem,
  TraceTurnView,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";
const WS_BASE =
  import.meta.env.VITE_WS_BASE ??
  API_BASE.replace(/^http:/, "ws:").replace(/^https:/, "wss:");

export class ApiError extends Error {
  status: number;
  code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

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
    let message = text || `Request failed: ${response.status}`;
    let code: string | undefined;
    try {
      const payload = JSON.parse(text) as { detail?: string | { message?: string; code?: string } };
      if (typeof payload.detail === "string") {
        message = payload.detail;
      } else if (payload.detail) {
        message = payload.detail.message || message;
        code = payload.detail.code;
      }
    } catch {
      // Preserve the response text when the server did not return JSON.
    }
    throw new ApiError(message, response.status, code);
  }
  return response.json() as Promise<T>;
}

export async function listSessions(): Promise<SessionSummary[]> {
  const data = await requestJson<{ sessions: SessionSummary[] }>("/sessions");
  return data.sessions;
}

export async function createSession(workspace?: string): Promise<SessionSummary> {
  const data = await requestJson<{ session: SessionSummary }>("/sessions", {
    method: "POST",
    body: workspace ? JSON.stringify({ workspace }) : undefined,
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

export async function getModelConfig(): Promise<ModelConfigView> {
  const data = await requestJson<{ model_config: ModelConfigView }>("/runtime/model");
  return data.model_config;
}

export async function getSessionModelConfig(sessionId: string): Promise<ModelConfigView> {
  const data = await requestJson<{ model_config: ModelConfigView }>(`/sessions/${sessionId}/model`);
  return data.model_config;
}

export async function listModelProviders(): Promise<ModelProviderView[]> {
  const data = await requestJson<{ providers: ModelProviderView[] }>("/runtime/model/providers");
  return data.providers;
}

export function listProviderModels(provider: string): Promise<ProviderModelsView> {
  return requestJson<ProviderModelsView>(
    `/runtime/model/providers/${encodeURIComponent(provider)}/models`,
  );
}

export async function browseWorkspace(path?: string): Promise<DirectoryBrowseView> {
  const data = await requestJson<DirectoryBrowseView>("/runtime/workspace/browse", {
    method: "POST",
    body: path ? JSON.stringify({ path }) : undefined,
  });
  return data;
}

export async function updateSessionModel(
  sessionId: string,
  provider: string,
  model: string,
): Promise<ModelConfigView> {
  const data = await requestJson<{ model_config: ModelConfigView }>(`/sessions/${sessionId}/model`, {
    method: "POST",
    body: JSON.stringify({ provider, model }),
  });
  return data.model_config;
}

export function listMcpTools(sessionId: string): Promise<McpToolsView> {
  return requestJson<McpToolsView>(`/sessions/${sessionId}/mcp-tools`);
}

export function reloadMcpTools(sessionId: string): Promise<McpReloadView> {
  return requestJson<McpReloadView>(`/sessions/${sessionId}/mcp/reload`, {
    method: "POST",
  });
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

export async function getTraceTimeline(
  sessionId: string,
  turnId?: string | null,
): Promise<TraceTimelineItem[]> {
  const query = turnId ? `?turn_id=${encodeURIComponent(turnId)}` : "";
  const data = await requestJson<{ timeline: TraceTimelineItem[] }>(
    `/sessions/${sessionId}/trace${query}`,
  );
  return data.timeline;
}

export async function getTraceTurns(sessionId: string): Promise<TraceTurnView[]> {
  const data = await requestJson<{ turns: TraceTurnView[] }>(
    `/sessions/${sessionId}/trace/turns`,
  );
  return data.turns;
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
