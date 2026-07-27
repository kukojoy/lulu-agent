export type SessionSummary = {
  session_id: string;
  updated_at?: string;
  created_at?: string;
  cwd?: string;
  title?: string;
  message_count?: number;
};

export type TranscriptMessage = {
  role?: string;
  content?: string | null;
  has_tool_calls?: boolean;
  tool_call_id?: string;
  turn_id?: string;
  tool_calls?: unknown[];
};

export type SessionInspection = {
  metadata: SessionSummary;
  message_count: number;
  turn_count?: number;
  compression_count?: number;
  task_state_count?: number;
  messages: TranscriptMessage[];
};

export type TaskStep = {
  id: number;
  step: string;
  status: string;
};

export type TaskState = {
  goal: string;
  status: string;
  steps: TaskStep[];
  blockers: string[];
  verified: string[];
  next_action: string;
};

export type RuntimeState = {
  session_id: string;
  running: boolean;
  connected: boolean;
};

export type MemoryEntry = {
  id: number;
  kind: string;
  content: string;
  updated_at: string;
};

export type MemoryView = {
  ok: boolean;
  message?: string;
  path: string;
  content: string;
  entries: MemoryEntry[];
  entry_count: number;
  truncated: boolean;
  original_length: number;
};

export type SkillMetadata = {
  name: string;
  description: string;
  path: string;
  directory: string;
};

export type SkillLoadError = {
  path: string;
  error: string;
};

export type SkillListView = {
  root: string;
  skills: SkillMetadata[];
  errors: SkillLoadError[];
};

export type SkillDocument = {
  name: string;
  description: string;
  path: string;
  directory: string;
  content: string;
};

export type TraceTimelineItem = {
  event_type?: string;
  turn_id?: string;
  timestamp?: string;
  label?: string;
  detail?: string;
  tool_name?: string;
  tool_call_id?: string;
  ok?: boolean;
  error?: string | null;
  error_type?: string | null;
  payload?: Record<string, unknown>;
};

export type RuntimeEvent = {
  type: string;
  turn_id: string;
  timestamp: string;
  payload: Record<string, unknown>;
};

export type ToolCallView = {
  id?: string;
  toolName: string;
  arguments: unknown;
};

export type ChatItem =
  | {
      id: string;
      kind: "user" | "assistant";
      content: string;
    }
  | {
      id: string;
      kind: "tool_call";
      title: string;
      assistantContent: string;
      toolCalls: ToolCallView[];
    }
  | {
      id: string;
      kind: "tool_result";
      title: string;
      toolResult: unknown;
    };
