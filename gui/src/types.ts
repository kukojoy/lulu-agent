export type SessionSummary = {
  session_id: string;
  updated_at?: string;
  created_at?: string;
  cwd?: string;
  title?: string;
  message_count?: number;
  active?: boolean;
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
  turns?: TurnInspection[];
};

export type TurnInspection = {
  turn_id: string;
  status: string;
  exit_reason?: string | null;
  error?: string | null;
  error_type?: string | null;
  final_response?: string;
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
  active?: boolean;
  running: boolean;
  connected: boolean;
  active_turn_id?: string | null;
  status?: string | null;
  status_detail?: string | null;
  pending_approval?: ApprovalRequestView | null;
  notices?: string[];
};

export type ModelConfigView = {
  provider: string;
  model: string;
  base_url_host: string;
  timeout_seconds: number;
  max_retries: number;
};

export type ModelProviderView = {
  name: string;
  base_url_host: string;
  default_model: string;
  base_url_configured: boolean;
  api_key_configured: boolean;
};

export type ProviderModelsView = {
  provider: string;
  models: string[];
  discovered: boolean;
  error?: string | null;
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

export type SkillLoadIssue = {
  path: string;
  issue_message: string;
};

export type SkillListView = {
  root: string;
  skills: SkillMetadata[];
  load_issues: SkillLoadIssue[];
};

export type SkillDocument = {
  name: string;
  description: string;
  path: string;
  directory: string;
  content: string;
};

export type McpToolView = {
  name: string;
  description: string;
};

export type McpServerToolsView = {
  name: string;
  safety_profile?: string;
  tools: McpToolView[];
};

export type McpToolsView = {
  servers: McpServerToolsView[];
};

export type McpReloadIssue = {
  server: string;
  issue_message: string;
};

export type McpReloadView = {
  registered: string[];
  issues: McpReloadIssue[];
  tools: McpToolsView;
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

export type ApprovalRequestView = {
  request_id: string;
  category: string;
  reason: string;
  subject: string;
};

export type ToolCallView = {
  id?: string;
  toolName: string;
  arguments: unknown;
};

export type ChatItem =
  | {
      id: string;
      kind: "user" | "assistant" | "runtime_error";
      content: string;
      errorType?: string | null;
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
