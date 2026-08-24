import {
  Activity,
  AlertCircle,
  ArrowUp,
  Bot,
  BookOpen,
  Brain,
  Check,
  ChevronDown,
  ChevronRight,
  Folder,
  History,
  ListTree,
  LockKeyhole,
  MessageSquarePlus,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  RefreshCcw,
  Send,
  Square,
  Trash2,
  Wrench,
  X,
} from "lucide-react";
import { FormEvent, KeyboardEvent, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, PointerEvent as ReactPointerEvent, ReactNode } from "react";

import {
  ApiError,
  browseWorkspace,
  createSession,
  deleteSession,
  getMemory,
  getModelConfig,
  getRuntimeState,
  getSessionModelConfig,
  getTaskState,
  getTraceTurns,
  getTraceTimeline,
  listModelProviders,
  listMcpTools,
  listProviderModels,
  inspectSession,
  listSkills,
  listSessions,
  loadMessages,
  openRunSocket,
  readSkill,
  reloadMcpTools,
  updateSessionModel,
} from "./api";
import type {
  ApprovalRequestView,
  ChatItem,
  DirectoryBrowseView,
  MemoryView,
  McpToolsView,
  ModelConfigView,
  ModelProviderView,
  ProviderModelsView,
  RuntimeState,
  SkillDocument,
  SkillListView,
  SessionInspection,
  SessionSummary,
  TaskState,
  ToolCallView,
  TranscriptMessage,
  TraceTurnView,
} from "./types";

type InspectorView = "trace" | "task" | "memory" | "skills" | "mcp";
type ConnectionStatus = "draft" | "connecting" | "ready" | "reconnecting";
type SessionWorkspaceGroup = {
  key: string;
  label: string;
  title: string;
  sessions: SessionSummary[];
};

const RUN_SOCKET_RECONNECT_DELAYS_MS = [500, 1000, 2000, 4000];

function formatDetails(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function formatTraceTimestamp(value?: string | null): string {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value.replace("T", " ").replace(/\.\d+/, "").replace(/([+-]\d{2}:\d{2}|Z)$/, "");
  }
  const pad = (part: number) => String(part).padStart(2, "0");
  return [
    date.getFullYear(),
    pad(date.getMonth() + 1),
    pad(date.getDate()),
  ].join("-") + ` ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function formatDate(value?: string | null): string {
  return formatTraceTimestamp(value).split(" ")[0];
}

function workspaceLabel(cwd?: string | null): string {
  if (!cwd) {
    return "No workspace";
  }
  if (cwd === "/") {
    return "Root";
  }
  const parts = cwd.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] || cwd;
}

type TraceTimelineItemView = TraceTurnView["items"][number];
type TraceDetailField = { label: string; value: string };

function traceTurnStatusClass(turn: TraceTurnView): string {
  if (turn.status === "failed" || turn.status === "interrupted" || turn.error || turn.error_type) {
    return "failed";
  }
  if (turn.status === "running") {
    return "running";
  }
  return "completed";
}

function tracePayloadValue(item: TraceTimelineItemView, key: string): unknown {
  return item.payload?.[key];
}

function traceReviewBadge(turn: TraceTurnView): { label: string; className: string; title: string } | null {
  const reviewItems = turn.items.filter((item) => item.event_type === "review_summary");
  if (reviewItems.length === 0) {
    return null;
  }
  const reviewers = Array.from(
    new Set(reviewItems.map((item) => String(tracePayloadValue(item, "reviewer") || "review"))),
  );
  const hasFailed = reviewItems.some((item) => tracePayloadValue(item, "status") === "failed");
  const hasChanged = reviewItems.some((item) => tracePayloadValue(item, "changed") === true);
  if (hasFailed) {
    return { label: "review failed", className: "failed", title: reviewers.join(", ") };
  }
  if (hasChanged) {
    return { label: "review updated", className: "changed", title: reviewers.join(", ") };
  }
  return { label: "reviewed", className: "done", title: reviewers.join(", ") };
}

function traceDetailFieldClass(field: TraceDetailField): string {
  return field.label === "error_type" ? "error-type" : "";
}

function traceDetailFields(item: TraceTimelineItemView): TraceDetailField[] {
  if (item.event_type === "model_request") {
    return [
      { label: "model", value: String(tracePayloadValue(item, "model") ?? "-") },
      { label: "messages", value: String(tracePayloadValue(item, "message_count") ?? 0) },
      { label: "tools", value: String(tracePayloadValue(item, "tool_count") ?? 0) },
    ];
  }
  if (item.event_type === "model_retry") {
    return [
      {
        label: "attempt",
        value: `${String(tracePayloadValue(item, "attempt") ?? 0)}/${String(tracePayloadValue(item, "max_retries") ?? 0)}`,
      },
      { label: "error_type", value: String(tracePayloadValue(item, "error_type") ?? "-") },
    ];
  }
  if (item.event_type === "assistant_message") {
    return [
      { label: "tool_calls", value: String(tracePayloadValue(item, "tool_call_count") ?? 0) },
      { label: "final", value: String(tracePayloadValue(item, "final") ?? false) },
      { label: "streamed", value: String(tracePayloadValue(item, "streamed") ?? false) },
    ];
  }
  if (item.event_type === "tool_call") {
    return [
      { label: "tool", value: String(tracePayloadValue(item, "tool_name") || "-") },
      { label: "call_id", value: String(tracePayloadValue(item, "tool_call_id") || "-") },
    ];
  }
  if (item.event_type === "tool_result") {
    const fields = [
      { label: "tool", value: String(tracePayloadValue(item, "tool_name") || "-") },
      { label: "ok", value: String(tracePayloadValue(item, "ok") ?? false) },
    ];
    const errorType = tracePayloadValue(item, "error_type");
    if (errorType) {
      fields.push({ label: "error_type", value: String(errorType) });
    }
    return fields;
  }
  if (item.event_type === "turn_end") {
    return [
      { label: "status", value: String(tracePayloadValue(item, "status") ?? "-") },
      { label: "exit_reason", value: String(tracePayloadValue(item, "exit_reason") ?? "-") },
    ];
  }
  if (item.event_type === "review_summary") {
    return [
      { label: "reviewer", value: String(tracePayloadValue(item, "reviewer") ?? "-") },
      { label: "status", value: String(tracePayloadValue(item, "status") ?? "-") },
      { label: "changed", value: String(tracePayloadValue(item, "changed") ?? "-") },
    ];
  }
  return [];
}

function traceDetailText(item: TraceTimelineItemView): string {
  if (item.event_type === "user_message") {
    return String(tracePayloadValue(item, "content") || "");
  }
  if (item.event_type === "assistant_message") {
    return String(tracePayloadValue(item, "content") || "");
  }
  if (item.event_type === "tool_call") {
    return formatDetails(tracePayloadValue(item, "arguments") ?? {});
  }
  if (item.event_type === "tool_result") {
    return String(tracePayloadValue(item, "error") || "");
  }
  if (item.event_type === "turn_end") {
    return String(tracePayloadValue(item, "error") || "");
  }
  if (item.event_type === "review_summary") {
    return String(tracePayloadValue(item, "message") || "");
  }
  if (
    item.event_type === "model_request" ||
    item.event_type === "model_retry" ||
    item.event_type === "tool_result"
  ) {
    return "";
  }
  return "";
}

function parseJsonValue(value: unknown): unknown {
  if (typeof value !== "string") {
    return value ?? {};
  }
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

function runtimeToolItem(
  event: { type: string; turn_id: string; payload: Record<string, unknown> },
  assistantContent = "",
): ChatItem | null {
  const payload = event.payload;
  const toolCallId = String(payload.tool_call_id ?? "");
  const toolName = String(payload.tool_name ?? "tool");
  if (event.type === "tool_call") {
    return {
      id: `live-${event.turn_id}-${toolCallId}-call`,
      kind: "tool_call",
      title: `Tool call · ${toolName}`,
      assistantContent,
      toolCalls: [
        {
          id: toolCallId,
          toolName,
          arguments: payload.arguments ?? {},
        },
      ],
    };
  }
  if (event.type === "tool_result") {
    return {
      id: `live-${event.turn_id}-${toolCallId}-result`,
      kind: "tool_result",
      title: `Tool result · ${toolName}`,
      toolResult: {
        ok: payload.ok,
        output: payload.output,
        error: payload.error,
        metadata: payload.metadata,
      },
    };
  }
  return null;
}

function runtimeStateFromPayload(value: unknown): RuntimeState | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const candidate = value as Partial<RuntimeState>;
  if (typeof candidate.session_id !== "string") {
    return null;
  }
  return {
    session_id: candidate.session_id,
    active: Boolean(candidate.active),
    running: Boolean(candidate.running),
    connected: Boolean(candidate.connected),
    active_turn_id:
      typeof candidate.active_turn_id === "string" ? candidate.active_turn_id : null,
    status: typeof candidate.status === "string" ? candidate.status : null,
    status_detail: typeof candidate.status_detail === "string" ? candidate.status_detail : null,
    pending_approval:
      candidate.pending_approval && typeof candidate.pending_approval === "object"
        ? approvalRequestFromPayload(candidate.pending_approval as Record<string, unknown>)
        : null,
    notices: Array.isArray(candidate.notices)
      ? candidate.notices.filter((notice): notice is string => typeof notice === "string")
      : [],
  };
}

function approvalRequestFromPayload(payload: Record<string, unknown>): ApprovalRequestView | null {
  const requestId = payload.request_id;
  if (typeof requestId !== "string" || !requestId) {
    return null;
  }
  return {
    request_id: requestId,
    category: String(payload.category ?? "approval"),
    reason: String(payload.reason ?? ""),
    subject: String(payload.subject ?? ""),
  };
}

function formatServerError(payload: Record<string, unknown>): string {
  const message = String(payload.message ?? "Event stream error");
  const code = typeof payload.code === "string" ? payload.code : "";
  if (code === "session_running") {
    return "This session is already running.";
  }
  if (code === "invalid_command") {
    return "The server rejected an unsupported command.";
  }
  if (code === "invalid_message") {
    return "Message content must be non-empty.";
  }
  if (code === "session_not_found") {
    return "Session not found.";
  }
  if (code === "configuration_error") {
    return `Configuration error: ${message}`;
  }
  if (code === "approval_not_found") {
    return "Approval request is no longer pending.";
  }
  if (code === "interrupt_unavailable") {
    return "There is no running turn to interrupt.";
  }
  return message;
}

function modelProviderReady(provider: ModelProviderView | undefined): boolean {
  return Boolean(provider?.base_url_configured && provider.api_key_configured);
}

function modelProviderMissingFields(provider: ModelProviderView | undefined): string {
  if (!provider) {
    return "provider configuration";
  }
  const missing = [];
  if (!provider.base_url_configured) {
    missing.push("base URL");
  }
  if (!provider.api_key_configured) {
    missing.push("API key");
  }
  return missing.join(" and ");
}

function modelProviderMissingLabel(provider: ModelProviderView): string {
  const missing = modelProviderMissingFields(provider);
  return missing ? `Missing ${missing}` : provider.base_url_host;
}

function renderInlineMarkdown(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /(`([^`]+)`|\*\*([^*]+)\*\*|\[([^\]]+)\]\((https?:\/\/[^)]+)\))/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }
    if (match[2]) {
      nodes.push(<code key={`${keyPrefix}-code-${match.index}`}>{match[2]}</code>);
    } else if (match[3]) {
      nodes.push(<strong key={`${keyPrefix}-strong-${match.index}`}>{match[3]}</strong>);
    } else if (match[4] && match[5]) {
      nodes.push(
        <a key={`${keyPrefix}-link-${match.index}`} href={match[5]} rel="noreferrer" target="_blank">
          {match[4]}
        </a>,
      );
    }
    lastIndex = pattern.lastIndex;
  }

  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }
  return nodes;
}

function tableCells(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function isTableSeparator(line: string): boolean {
  return tableCells(line).every((cell) => /^:?-{3,}:?$/.test(cell));
}

function MarkdownContent({ content }: { content: string }) {
  const lines = content.split(/\r?\n/);
  const blocks: ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();
    if (!trimmed) {
      index += 1;
      continue;
    }

    if (trimmed.startsWith("```")) {
      const language = trimmed.slice(3).trim();
      const codeLines: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith("```")) {
        codeLines.push(lines[index]);
        index += 1;
      }
      index += index < lines.length ? 1 : 0;
      blocks.push(
        <pre className="markdown-code" key={`code-${index}`}>
          <code>{codeLines.join("\n") || language}</code>
        </pre>,
      );
      continue;
    }

    const heading = /^(#{1,3})\s+(.+)$/.exec(trimmed);
    if (heading) {
      const level = heading[1].length;
      const HeadingTag = `h${level + 2}` as "h3" | "h4" | "h5";
      blocks.push(
        <HeadingTag key={`heading-${index}`}>
          {renderInlineMarkdown(heading[2], `heading-${index}`)}
        </HeadingTag>,
      );
      index += 1;
      continue;
    }

    if (trimmed.startsWith("|") && lines[index + 1] && isTableSeparator(lines[index + 1])) {
      const headers = tableCells(trimmed);
      const rows: string[][] = [];
      index += 2;
      while (index < lines.length && lines[index].trim().startsWith("|")) {
        rows.push(tableCells(lines[index]));
        index += 1;
      }
      blocks.push(
        <div className="markdown-table-wrap" key={`table-${index}`}>
          <table>
            <thead>
              <tr>
                {headers.map((header, headerIndex) => (
                  <th key={`head-${headerIndex}`}>
                    {renderInlineMarkdown(header, `table-${index}-head-${headerIndex}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={`row-${rowIndex}`}>
                  {row.map((cell, cellIndex) => (
                    <td key={`cell-${rowIndex}-${cellIndex}`}>
                      {renderInlineMarkdown(cell, `table-${index}-${rowIndex}-${cellIndex}`)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }

    if (/^[-*]\s+/.test(trimmed)) {
      const items: string[] = [];
      while (index < lines.length && /^[-*]\s+/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^[-*]\s+/, ""));
        index += 1;
      }
      blocks.push(
        <ul key={`ul-${index}`}>
          {items.map((item, itemIndex) => (
            <li key={`li-${itemIndex}`}>{renderInlineMarkdown(item, `ul-${index}-${itemIndex}`)}</li>
          ))}
        </ul>,
      );
      continue;
    }

    if (/^\d+\.\s+/.test(trimmed)) {
      const items: string[] = [];
      while (index < lines.length && /^\d+\.\s+/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^\d+\.\s+/, ""));
        index += 1;
      }
      blocks.push(
        <ol key={`ol-${index}`}>
          {items.map((item, itemIndex) => (
            <li key={`li-${itemIndex}`}>{renderInlineMarkdown(item, `ol-${index}-${itemIndex}`)}</li>
          ))}
        </ol>,
      );
      continue;
    }

    const paragraphLines = [trimmed];
    index += 1;
    while (index < lines.length && lines[index].trim()) {
      const nextLine = lines[index].trim();
      if (
        nextLine.startsWith("```") ||
        /^(#{1,3})\s+/.test(nextLine) ||
        /^[-*]\s+/.test(nextLine) ||
        /^\d+\.\s+/.test(nextLine) ||
        (nextLine.startsWith("|") && lines[index + 1] && isTableSeparator(lines[index + 1]))
      ) {
        break;
      }
      paragraphLines.push(nextLine);
      index += 1;
    }
    blocks.push(
      <p key={`p-${index}`}>{renderInlineMarkdown(paragraphLines.join("\n"), `p-${index}`)}</p>,
    );
  }

  return <div className="markdown-body">{blocks.length ? blocks : <p>[empty]</p>}</div>;
}

function transcriptToChatItems(messages: TranscriptMessage[], inspection: SessionInspection | null): ChatItem[] {
  const errorTurns = new Map(
    (inspection?.turns ?? [])
      .filter((turn) => turn.error)
      .map((turn) => [
        turn.turn_id,
        {
          content: turn.final_response || turn.error || "Agent runtime error",
          errorType: turn.error_type,
        },
      ]),
  );
  const lastMessageIndexByTurn = new Map<string, number>();
  messages.forEach((message, index) => {
    if (message.turn_id) {
      lastMessageIndexByTurn.set(message.turn_id, index);
    }
  });

  return messages.flatMap((message, index) => {
      if (message.role === "system") {
        return [];
      }
      const id = `${message.turn_id ?? "message"}-${message.tool_call_id ?? message.role ?? "item"}-${index}`;
      let item: ChatItem;
      if (message.role === "tool") {
        item = {
          id,
          kind: "tool_result",
          title: `Tool result${message.tool_call_id ? ` · ${message.tool_call_id}` : ""}`,
          toolResult: parseJsonValue(message.content),
        };
      } else if (message.role === "assistant" && message.tool_calls?.length) {
        const toolCalls: ToolCallView[] = message.tool_calls.map((toolCall) => {
          const candidate = toolCall as {
            id?: string;
            function?: {
              name?: string;
              arguments?: unknown;
            };
          };
          return {
            id: candidate.id,
            toolName: candidate.function?.name ?? "tool",
            arguments: parseJsonValue(candidate.function?.arguments),
          };
        });
        item = {
          id,
          kind: "tool_call",
          title: `Tool call · ${message.tool_calls.length}`,
          assistantContent: typeof message.content === "string" ? message.content : "",
          toolCalls,
        };
      } else {
        item = {
          id,
          kind: message.role === "assistant" ? "assistant" : "user",
          content: typeof message.content === "string" ? message.content : "",
        };
      }

      const runtimeError = message.turn_id ? errorTurns.get(message.turn_id) : null;
      if (runtimeError && lastMessageIndexByTurn.get(message.turn_id ?? "") === index) {
        return [
          item,
          {
            id: `${message.turn_id}-runtime-error`,
            kind: "runtime_error",
            content: runtimeError.content,
            errorType: runtimeError.errorType,
          },
        ];
      }
      return [item];
    });
}

export function App() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState("");
  const [inspection, setInspection] = useState<SessionInspection | null>(null);
  const [messages, setMessages] = useState<TranscriptMessage[]>([]);
  const [taskState, setTaskState] = useState<TaskState | null>(null);
  const [traceTurns, setTraceTurns] = useState<TraceTurnView[]>([]);
  const [runtimeState, setRuntimeState] = useState<RuntimeState | null>(null);
  const [modelConfig, setModelConfig] = useState<ModelConfigView | null>(null);
  const [modelProviders, setModelProviders] = useState<ModelProviderView[]>([]);
  const [selectedModelProvider, setSelectedModelProvider] = useState("");
  const [providerListOpen, setProviderListOpen] = useState(false);
  const [providerModels, setProviderModels] = useState<ProviderModelsView | null>(null);
  const [modelDraft, setModelDraft] = useState("");
  const [modelListOpen, setModelListOpen] = useState(false);
  const [modelSearch, setModelSearch] = useState("");
  const [modelListLoading, setModelListLoading] = useState(false);
  const [modelPanelOpen, setModelPanelOpen] = useState(false);
  const [modelSwitchingSessionId, setModelSwitchingSessionId] = useState("");
  const [memoryView, setMemoryView] = useState<MemoryView | null>(null);
  const [mcpTools, setMcpTools] = useState<McpToolsView | null>(null);
  const [mcpReloadingSessionId, setMcpReloadingSessionId] = useState("");
  const [skillList, setSkillList] = useState<SkillListView | null>(null);
  const [selectedSkill, setSelectedSkill] = useState<SkillDocument | null>(null);
  const [liveToolItems, setLiveToolItems] = useState<ChatItem[]>([]);
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const [taskOpen, setTaskOpen] = useState(false);
  const [inspectorWidth, setInspectorWidth] = useState(560);
  const [inspectorView, setInspectorView] = useState<InspectorView>("trace");
  const [draft, setDraft] = useState("");
  const [workspaceDraft, setWorkspaceDraft] = useState("");
  const [workspacePickerOpen, setWorkspacePickerOpen] = useState(false);
  const [workspaceBrowser, setWorkspaceBrowser] = useState<DirectoryBrowseView | null>(null);
  const [workspaceBrowserLoading, setWorkspaceBrowserLoading] = useState(false);
  const [workspaceBrowserError, setWorkspaceBrowserError] = useState("");
  const [collapsedWorkspaceGroups, setCollapsedWorkspaceGroups] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [creatingSession, setCreatingSession] = useState(false);
  const [error, setError] = useState("");
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("draft");
  const [streamingMessage, setStreamingMessage] = useState("");
  const [approvalRequest, setApprovalRequest] = useState<ApprovalRequestView | null>(null);
  const [expandedMessages, setExpandedMessages] = useState<Set<string>>(new Set());
  const [expandedTraceTurns, setExpandedTraceTurns] = useState<Set<string>>(new Set());
  const [expandedMcpServers, setExpandedMcpServers] = useState<Set<string>>(new Set());
  const socketRef = useRef<WebSocket | null>(null);
  const chatEndRef = useRef<HTMLDivElement | null>(null);
  const composerTextareaRef = useRef<HTMLTextAreaElement | null>(null);
  const modelConfigButtonRef = useRef<HTMLButtonElement | null>(null);
  const pendingFirstMessageRef = useRef<{ sessionId: string; content: string } | null>(null);
  const runningSessionIdRef = useRef("");
  const pendingSentMessageRef = useRef("");
  const pendingToolReasoningRef = useRef("");
  const lastRuntimeErrorRef = useRef<{ sessionId: string; message: string } | null>(null);
  const activeSessionIdRef = useRef("");
  const creatingSessionRef = useRef(false);
  const sessionSelectionGenerationRef = useRef(0);
  const modelStateRequestRef = useRef(0);
  const modelActionRequestRef = useRef(0);
  const mcpActionRequestRef = useRef(0);
  const providerModelsRequestRef = useRef(0);
  const defaultWorkspaceRef = useRef("");
  const reconnectTimerRef = useRef<number | null>(null);
  const inspectorResizeRef = useRef({ startX: 0, startWidth: 0 });
  const [modelPanelStyle, setModelPanelStyle] = useState<CSSProperties>({});
  const activeSession = sessions.find((session) => session.session_id === activeSessionId);
  const activeSessionLocked = Boolean(activeSession?.locked);

  const setSessionError = useCallback((
    sessionId: string,
    message: string,
    generation?: number,
  ) => {
    if (
      activeSessionIdRef.current === sessionId &&
      (generation === undefined || sessionSelectionGenerationRef.current === generation)
    ) {
      setError(message);
    }
  }, []);

  const selectSession = useCallback((sessionId: string) => {
    if (activeSessionIdRef.current === sessionId) {
      setError("");
      return;
    }
    sessionSelectionGenerationRef.current += 1;
    activeSessionIdRef.current = sessionId;
    setError("");
    setActiveSessionId(sessionId);
  }, []);

  const isCurrentSessionSelection = useCallback(
    (sessionId: string, generation: number) =>
      activeSessionIdRef.current === sessionId &&
      sessionSelectionGenerationRef.current === generation,
    [],
  );

  const finishCreatingSession = useCallback(() => {
    creatingSessionRef.current = false;
    setCreatingSession(false);
  }, []);

  const markSessionLocked = useCallback((sessionId: string, message: string) => {
    setSessions((current) =>
      current.map((session) =>
        session.session_id === sessionId
          ? {
              ...session,
              active: false,
              locked: true,
              lock_message: message,
            }
          : session,
      ),
    );
  }, []);

  const applyRuntimeState = useCallback((nextRuntimeState: RuntimeState) => {
    setRuntimeState(nextRuntimeState);
    if (nextRuntimeState.running) {
      runningSessionIdRef.current = nextRuntimeState.session_id;
      setBusy(true);
    } else if (runningSessionIdRef.current === nextRuntimeState.session_id) {
      runningSessionIdRef.current = "";
      pendingSentMessageRef.current = "";
      setBusy(false);
    }
    setApprovalRequest(nextRuntimeState.pending_approval ?? null);
  }, []);

  const resizeInspector = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!event.currentTarget.hasPointerCapture(event.pointerId)) {
      return;
    }
    const sidebarWidth = sessionsOpen ? 280 : 52;
    const minWidth = 360;
    const maxWidth = Math.max(minWidth, Math.min(720, window.innerWidth - sidebarWidth - 360));
    const nextWidth = inspectorResizeRef.current.startWidth + inspectorResizeRef.current.startX - event.clientX;
    setInspectorWidth(Math.max(minWidth, Math.min(maxWidth, nextWidth)));
  };

  const startInspectorResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    inspectorResizeRef.current = { startX: event.clientX, startWidth: inspectorWidth };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const loadWorkspaceBrowser = useCallback(async (path?: string) => {
    setWorkspaceBrowserLoading(true);
    setWorkspaceBrowserError("");
    try {
      const nextBrowser = await browseWorkspace(path);
      setWorkspaceBrowser(nextBrowser);
      return nextBrowser;
    } catch (nextError) {
      setWorkspaceBrowserError(String(nextError));
      return null;
    } finally {
      setWorkspaceBrowserLoading(false);
    }
  }, []);

  const closeWorkspacePicker = useCallback(() => {
    setWorkspacePickerOpen(false);
    setWorkspaceBrowserError("");
  }, []);

  const refreshSessions = useCallback(async () => {
    const nextSessions = await listSessions();
    setSessions(nextSessions);
  }, []);

  const handleSessionRequestError = useCallback(
    (sessionId: string, nextError: unknown, generation?: number) => {
      if (
        generation !== undefined &&
        !isCurrentSessionSelection(sessionId, generation)
      ) {
        return;
      }
      if (nextError instanceof ApiError && nextError.code === "session_workspace_unavailable") {
        setSessionError(sessionId, "", generation);
        markSessionLocked(sessionId, nextError.message);
        void refreshSessions().catch((refreshError) =>
          setSessionError(sessionId, String(refreshError), generation),
        );
        return;
      }
      setSessionError(sessionId, String(nextError), generation);
    },
    [isCurrentSessionSelection, markSessionLocked, refreshSessions, setSessionError],
  );

  const refreshModelRuntime = useCallback(async (isCurrent: () => boolean = () => true) => {
    const requestId = ++modelStateRequestRef.current;
    const canApply = () => modelStateRequestRef.current === requestId && isCurrent();
    const [configResult, providersResult] = await Promise.allSettled([
      getModelConfig(),
      listModelProviders(),
    ]);
    if (!canApply()) {
      return;
    }
    const nextProviders =
      providersResult.status === "fulfilled" ? providersResult.value : [];
    const nextConfig =
      configResult.status === "fulfilled" ? configResult.value : null;

    if (nextProviders.length) {
      setModelProviders(nextProviders);
    }
    if (nextConfig) {
      setModelConfig(nextConfig);
      setSelectedModelProvider(nextConfig.provider);
      setModelDraft(nextConfig.model);
      return;
    }

    const fallbackProvider =
      nextProviders.find((provider) => modelProviderReady(provider)) ?? nextProviders[0];
    if (fallbackProvider) {
      let fallbackModel = fallbackProvider.default_model || "";
      if (!fallbackModel && modelProviderReady(fallbackProvider)) {
        try {
          const discovered = await listProviderModels(fallbackProvider.name);
          if (!canApply()) {
            return;
          }
          fallbackModel = discovered.models[0] || "";
          setProviderModels(discovered);
        } catch {
          fallbackModel = "";
        }
      }
      setSelectedModelProvider(fallbackProvider.name);
      setModelDraft(fallbackModel);
      setModelConfig((current) => {
        if (current?.provider || current?.model) {
          return current;
        }
        return {
          provider: fallbackProvider.name,
          model: fallbackModel,
          base_url_host: fallbackProvider.base_url_host,
          timeout_seconds: current?.timeout_seconds ?? 60,
          max_retries: current?.max_retries ?? 0,
        };
      });
    }

    if (configResult.status === "rejected" && providersResult.status === "rejected") {
      throw configResult.reason;
    }
  }, []);

  const restoreStreamingMessageFromTrace = useCallback(
    async (
      sessionId: string,
      turnId: string | null | undefined,
      generation = sessionSelectionGenerationRef.current,
    ) => {
      if (!turnId) {
        return;
      }
      const timeline = await getTraceTimeline(sessionId, turnId);
      if (!isCurrentSessionSelection(sessionId, generation)) {
        return;
      }
      const restored = timeline
        .filter((item) => item.event_type === "assistant_delta")
        .map((item) => {
          const delta = item.payload?.delta;
          return typeof delta === "string" ? delta : "";
        })
        .join("");
      if (!restored) {
        return;
      }
      setStreamingMessage((current) => {
        if (!current) {
          return restored;
        }
        if (restored === current || restored.endsWith(current) || restored.includes(current)) {
          return restored;
        }
        if (current.startsWith(restored)) {
          return current;
        }
        return `${restored}${current}`;
      });
    },
    [isCurrentSessionSelection],
  );

  const refreshTraceTurns = useCallback(async () => {
    if (!activeSessionId || activeSessionLocked) {
      setTraceTurns([]);
      return;
    }
    const sessionId = activeSessionId;
    const generation = sessionSelectionGenerationRef.current;
    const nextTraceTurns = await getTraceTurns(sessionId);
    if (isCurrentSessionSelection(sessionId, generation)) {
      setTraceTurns(nextTraceTurns);
    }
  }, [activeSessionId, activeSessionLocked, isCurrentSessionSelection]);

  const refreshSession = useCallback(
    async (sessionId: string) => {
      const generation = sessionSelectionGenerationRef.current;
      const modelRequestId = ++modelStateRequestRef.current;
      const [
        nextInspection,
        nextMessages,
        nextTaskState,
        nextRuntimeState,
      ] = await Promise.all([
        inspectSession(sessionId),
        loadMessages(sessionId),
        getTaskState(sessionId),
        getRuntimeState(sessionId),
      ]);
      if (!isCurrentSessionSelection(sessionId, generation)) {
        return;
      }
      const nextModelConfig = await getSessionModelConfig(sessionId).catch(() => null);
      if (!isCurrentSessionSelection(sessionId, generation)) {
        return;
      }
      const nextTraceTurns = await getTraceTurns(sessionId).catch(() => []);
      if (!isCurrentSessionSelection(sessionId, generation)) {
        return;
      }
      setInspection(nextInspection);
      setMessages(nextMessages);
      setTaskState(nextTaskState);
      setTraceTurns(nextTraceTurns);
      applyRuntimeState(nextRuntimeState);
      if (nextModelConfig) {
        if (modelStateRequestRef.current === modelRequestId) {
          setModelConfig(nextModelConfig);
        }
      } else {
        await refreshModelRuntime(() => isCurrentSessionSelection(sessionId, generation));
      }
      if (!isCurrentSessionSelection(sessionId, generation)) {
        return;
      }
      if (!nextRuntimeState.active) {
        setMemoryView(null);
        setSkillList(null);
        setSelectedSkill(null);
        setMcpTools(null);
      }
      if (nextRuntimeState.running && nextRuntimeState.status === "streaming_assistant") {
        await restoreStreamingMessageFromTrace(
          sessionId,
          nextRuntimeState.active_turn_id,
          generation,
        );
      }
    },
    [
      applyRuntimeState,
      isCurrentSessionSelection,
      refreshModelRuntime,
      restoreStreamingMessageFromTrace,
    ],
  );

  const refreshActiveSession = useCallback(async () => {
    if (!activeSessionId) {
      setInspection(null);
      setMessages([]);
      setTaskState(null);
      setRuntimeState(null);
      setLiveToolItems([]);
      setTraceTurns([]);
      setMemoryView(null);
      setSkillList(null);
      setSelectedSkill(null);
      setMcpTools(null);
      return;
    }
    if (activeSessionLocked) {
      setInspection(null);
      setMessages([]);
      setTaskState(null);
      setRuntimeState(null);
      setLiveToolItems([]);
      setTraceTurns([]);
      setMemoryView(null);
      setSkillList(null);
      setSelectedSkill(null);
      setMcpTools(null);
      return;
    }
    if (pendingFirstMessageRef.current?.sessionId === activeSessionId) {
      return;
    }
    await refreshSession(activeSessionId);
  }, [activeSessionId, activeSessionLocked, refreshSession]);

  const refreshMemory = useCallback(async () => {
    if (!activeSessionId || runtimeState?.session_id !== activeSessionId || !runtimeState.active) {
      setMemoryView(null);
      return;
    }
    const sessionId = activeSessionId;
    const generation = sessionSelectionGenerationRef.current;
    const nextMemoryView = await getMemory();
    if (isCurrentSessionSelection(sessionId, generation)) {
      setMemoryView(nextMemoryView);
    }
  }, [activeSessionId, isCurrentSessionSelection, runtimeState?.active, runtimeState?.session_id]);

  const refreshTask = useCallback(async () => {
    if (!activeSessionId || runtimeState?.session_id !== activeSessionId || !runtimeState.active) {
      setTaskState(null);
      return;
    }
    const sessionId = activeSessionId;
    const generation = sessionSelectionGenerationRef.current;
    const nextTaskState = await getTaskState(sessionId);
    if (isCurrentSessionSelection(sessionId, generation)) {
      setTaskState(nextTaskState);
    }
  }, [activeSessionId, isCurrentSessionSelection, runtimeState?.active, runtimeState?.session_id]);

  const refreshSkills = useCallback(async () => {
    if (!activeSessionId || runtimeState?.session_id !== activeSessionId || !runtimeState.active) {
      setSkillList(null);
      setSelectedSkill(null);
      return;
    }
    const sessionId = activeSessionId;
    const generation = sessionSelectionGenerationRef.current;
    const nextSkillList = await listSkills();
    if (isCurrentSessionSelection(sessionId, generation)) {
      setSkillList(nextSkillList);
    }
  }, [activeSessionId, isCurrentSessionSelection, runtimeState?.active, runtimeState?.session_id]);

  const refreshMcpTools = useCallback(async () => {
    if (!activeSessionId || runtimeState?.session_id !== activeSessionId || !runtimeState.active) {
      setMcpTools(null);
      return;
    }
    const sessionId = activeSessionId;
    const generation = sessionSelectionGenerationRef.current;
    const nextMcpTools = await listMcpTools(sessionId);
    if (isCurrentSessionSelection(sessionId, generation)) {
      setMcpTools(nextMcpTools);
    }
  }, [activeSessionId, isCurrentSessionSelection, runtimeState?.active, runtimeState?.session_id]);

  const refreshProviderModels = useCallback(async (provider: string, fallbackModel = "") => {
    const requestId = ++providerModelsRequestRef.current;
    if (!provider) {
      setProviderModels(null);
      setModelListLoading(false);
      return;
    }
    setModelListLoading(true);
    try {
      const latestProviders = await listModelProviders();
      if (providerModelsRequestRef.current !== requestId) {
        return;
      }
      setModelProviders(latestProviders);
      const latestProvider = latestProviders.find((item) => item.name === provider);
      const nextFallbackModel = latestProvider?.default_model || fallbackModel;
      if (!modelProviderReady(latestProvider)) {
        setProviderModels({
          provider,
          models: nextFallbackModel ? [nextFallbackModel] : [],
          discovered: false,
          error: `Model provider '${provider}' requires ${modelProviderMissingFields(latestProvider)}.`,
        });
        return;
      }
      const result = await listProviderModels(provider);
      if (providerModelsRequestRef.current !== requestId) {
        return;
      }
      setProviderModels(result);
      const nextModel = result.models[0] || nextFallbackModel;
      if (nextModel) {
        setModelDraft((current) => (current.trim() ? current : nextModel));
      }
    } catch (nextError) {
      if (providerModelsRequestRef.current === requestId) {
        throw nextError;
      }
    } finally {
      if (providerModelsRequestRef.current === requestId) {
        setModelListLoading(false);
      }
    }
  }, []);

  const updateModelPanelPosition = useCallback(() => {
    const button = modelConfigButtonRef.current;
    if (!button) {
      return;
    }
    const rect = button.getBoundingClientRect();
    const mainPanel = document.querySelector(".main-panel")?.getBoundingClientRect();
    const minLeft = (mainPanel?.left ?? 0) + 16;
    const maxRight = (mainPanel?.right ?? window.innerWidth) - 16;
    const availableWidth = Math.max(260, maxRight - minLeft);
    const panelWidth = Math.min(320, availableWidth);
    const left = Math.max(minLeft, Math.min(rect.right - panelWidth, maxRight - panelWidth));
    const bottom = Math.max(16, window.innerHeight - rect.top + 10);
    setModelPanelStyle({
      width: panelWidth,
      left,
      bottom,
    });
  }, []);

  const applyModelSelection = useCallback(async () => {
    if (!selectedModelProvider || !modelDraft.trim()) {
      return;
    }
    const sessionId = activeSessionId;
    const generation = sessionSelectionGenerationRef.current;
    const actionRequestId = ++modelActionRequestRef.current;
    const modelRequestId = ++modelStateRequestRef.current;
    const latestProviders = await listModelProviders();
    if (
      modelStateRequestRef.current !== modelRequestId ||
      modelActionRequestRef.current !== actionRequestId ||
      !isCurrentSessionSelection(sessionId, generation)
    ) {
      return;
    }
    setModelProviders(latestProviders);
    const provider = latestProviders.find((item) => item.name === selectedModelProvider);
    if (!modelProviderReady(provider)) {
      setError(`Model provider '${selectedModelProvider}' requires ${modelProviderMissingFields(provider)}.`);
      setProviderModels({
        provider: selectedModelProvider,
        models: provider?.default_model ? [provider.default_model] : [],
        discovered: false,
        error: `Model provider '${selectedModelProvider}' requires ${modelProviderMissingFields(provider)}.`,
      });
      return;
    }
    if (!sessionId) {
      setModelConfig({
        provider: selectedModelProvider,
        model: modelDraft.trim(),
        base_url_host: provider?.base_url_host ?? "",
        timeout_seconds: modelConfig?.timeout_seconds ?? 60,
        max_retries: modelConfig?.max_retries ?? 0,
      });
      setModelPanelOpen(false);
      return;
    }
    setModelSwitchingSessionId(sessionId);
    try {
      const nextModelConfig = await updateSessionModel(
        sessionId,
        selectedModelProvider,
        modelDraft.trim(),
      );
      if (
        modelStateRequestRef.current !== modelRequestId ||
        modelActionRequestRef.current !== actionRequestId ||
        !isCurrentSessionSelection(sessionId, generation)
      ) {
        return;
      }
      setModelConfig(nextModelConfig);
      const nextRuntimeState = await getRuntimeState(sessionId);
      if (
        modelStateRequestRef.current !== modelRequestId ||
        modelActionRequestRef.current !== actionRequestId ||
        !isCurrentSessionSelection(sessionId, generation)
      ) {
        return;
      }
      applyRuntimeState(nextRuntimeState);
      setModelPanelOpen(false);
    } catch (nextError) {
      if (
        modelActionRequestRef.current !== actionRequestId ||
        !isCurrentSessionSelection(sessionId, generation)
      ) {
        return;
      }
      const latestProviders = await listModelProviders().catch(() => null);
      if (
        latestProviders &&
        modelActionRequestRef.current === actionRequestId &&
        isCurrentSessionSelection(sessionId, generation)
      ) {
        setModelProviders(latestProviders);
      }
      if (modelActionRequestRef.current === actionRequestId) {
        handleSessionRequestError(sessionId, nextError, generation);
      }
    } finally {
      if (modelActionRequestRef.current === actionRequestId) {
        setModelSwitchingSessionId((current) => (current === sessionId ? "" : current));
      }
    }
  }, [
    activeSessionId,
    applyRuntimeState,
    handleSessionRequestError,
    isCurrentSessionSelection,
    modelConfig?.max_retries,
    modelConfig?.timeout_seconds,
    modelDraft,
    selectedModelProvider,
  ]);

  const reloadMcpToolsForActiveSession = useCallback(async () => {
    if (!activeSessionId || runtimeState?.session_id !== activeSessionId || !runtimeState.active) {
      setMcpTools(null);
      return;
    }
    const sessionId = activeSessionId;
    const generation = sessionSelectionGenerationRef.current;
    const actionRequestId = ++mcpActionRequestRef.current;
    setMcpReloadingSessionId(sessionId);
    setMcpTools(null);
    try {
      const result = await reloadMcpTools(sessionId);
      if (
        mcpActionRequestRef.current !== actionRequestId ||
        !isCurrentSessionSelection(sessionId, generation)
      ) {
        return;
      }
      setMcpTools(result.tools);
      const nextRuntimeState = await getRuntimeState(sessionId);
      if (
        mcpActionRequestRef.current !== actionRequestId ||
        !isCurrentSessionSelection(sessionId, generation)
      ) {
        return;
      }
      applyRuntimeState(nextRuntimeState);
      refreshSessions().catch((nextError) =>
        setSessionError(sessionId, String(nextError), generation),
      );
    } catch (nextError) {
      if (mcpActionRequestRef.current === actionRequestId) {
        handleSessionRequestError(sessionId, nextError, generation);
      }
    } finally {
      if (mcpActionRequestRef.current === actionRequestId) {
        setMcpReloadingSessionId((current) => (current === sessionId ? "" : current));
      }
    }
  }, [
    activeSessionId,
    applyRuntimeState,
    handleSessionRequestError,
    isCurrentSessionSelection,
    refreshSessions,
    runtimeState?.active,
    runtimeState?.session_id,
  ]);

  const loadSkill = useCallback(async (name: string) => {
    if (!activeSessionId || runtimeState?.session_id !== activeSessionId || !runtimeState.active) {
      return;
    }
    const sessionId = activeSessionId;
    const generation = sessionSelectionGenerationRef.current;
    const nextSkill = await readSkill(name);
    if (isCurrentSessionSelection(sessionId, generation)) {
      setSelectedSkill(nextSkill);
    }
  }, [activeSessionId, isCurrentSessionSelection, runtimeState?.active, runtimeState?.session_id]);

  function toggleMcpServer(name: string) {
    setExpandedMcpServers((current) => {
      const next = new Set(current);
      if (next.has(name)) {
        next.delete(name);
      } else {
        next.add(name);
      }
      return next;
    });
  }

  const clearLiveTurnState = useCallback(() => {
    setStreamingMessage("");
    setLiveToolItems([]);
    setApprovalRequest(null);
    pendingToolReasoningRef.current = "";
  }, []);

  const appendStreamingDelta = useCallback((delta: string) => {
    setStreamingMessage((current) => `${current}${delta}`);
  }, []);

  const markSessionActive = useCallback((sessionId: string) => {
    setSessions((current) =>
      current.map((session) =>
        session.session_id === sessionId ? { ...session, active: true } : session,
      ),
    );
  }, []);

  const setLiveRuntimeStatus = useCallback(
    (status: string, turnId: string | null = null, statusDetail: string | null = null) => {
      if (!activeSessionId) {
        return;
      }
      markSessionActive(activeSessionId);
      runningSessionIdRef.current = activeSessionId;
      setBusy(true);
      setRuntimeState((current) => ({
        session_id: activeSessionId,
        active: true,
        running: true,
        connected: true,
        active_turn_id: turnId ?? (current?.session_id === activeSessionId ? current.active_turn_id ?? null : null),
        status,
        status_detail: statusDetail,
        pending_approval: current?.session_id === activeSessionId ? current.pending_approval ?? null : null,
        notices: current?.session_id === activeSessionId ? current.notices : [],
      }));
    },
    [activeSessionId, markSessionActive],
  );

  const runSessionMessage = useCallback(
    (sessionId: string, content: string) => {
      if (!socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) {
        setSessionError(sessionId, "Run socket is not ready.");
        clearLiveTurnState();
        runningSessionIdRef.current = "";
        setBusy(false);
        return;
      }
      runningSessionIdRef.current = sessionId;
      setBusy(true);
      setRuntimeState((current) => ({
        session_id: sessionId,
        active: true,
        running: true,
        connected: true,
        active_turn_id: current?.session_id === sessionId ? current.active_turn_id ?? null : null,
        status: current?.session_id === sessionId ? current.status ?? null : null,
        status_detail: current?.session_id === sessionId ? current.status_detail ?? null : null,
        pending_approval: null,
        notices: current?.session_id === sessionId ? current.notices : [],
      }));
      socketRef.current.send(JSON.stringify({ type: "user_message", content }));
    },
    [clearLiveTurnState, setSessionError],
  );

  useLayoutEffect(() => {
    activeSessionIdRef.current = activeSessionId;
    setError("");
  }, [activeSessionId]);

  useEffect(() => {
    refreshSessions().catch((nextError) => setError(String(nextError)));
  }, [refreshSessions]);

  useEffect(() => {
    browseWorkspace()
      .then((workspace) => {
        defaultWorkspaceRef.current = workspace.path;
        setWorkspaceDraft((current) => current || workspace.path);
      })
      .catch((nextError) => setError(String(nextError)));
  }, []);

  useEffect(() => {
    refreshModelRuntime().catch((nextError) => setError(String(nextError)));
  }, [refreshModelRuntime]);

  useEffect(() => {
    if (!modelPanelOpen || !selectedModelProvider) {
      return;
    }
    updateModelPanelPosition();
    refreshProviderModels(selectedModelProvider).catch((nextError) => setError(String(nextError)));
  }, [modelPanelOpen, refreshProviderModels, selectedModelProvider, updateModelPanelPosition]);

  useEffect(() => {
    if (!modelPanelOpen) {
      return;
    }
    updateModelPanelPosition();
  }, [inspectorWidth, modelPanelOpen, sessionsOpen, taskOpen, updateModelPanelPosition]);

  useEffect(() => {
    if (!modelPanelOpen) {
      return;
    }
    window.addEventListener("resize", updateModelPanelPosition);
    window.addEventListener("scroll", updateModelPanelPosition, true);
    return () => {
      window.removeEventListener("resize", updateModelPanelPosition);
      window.removeEventListener("scroll", updateModelPanelPosition, true);
    };
  }, [modelPanelOpen, updateModelPanelPosition]);

  useEffect(() => {
    if (!modelPanelOpen && modelConfig?.model) {
      setModelDraft(modelConfig.model);
      if (modelConfig.provider) {
        setSelectedModelProvider(modelConfig.provider);
      }
      setProviderListOpen(false);
      setModelListOpen(false);
      setModelSearch("");
    }
  }, [modelConfig?.model, modelConfig?.provider, modelPanelOpen]);

  useEffect(() => {
    const sessionId = activeSessionId;
    const generation = sessionSelectionGenerationRef.current;
    refreshActiveSession().catch((nextError) =>
      handleSessionRequestError(sessionId, nextError, generation),
    );
  }, [activeSessionId, handleSessionRequestError, refreshActiveSession]);

  useEffect(() => {
    setExpandedTraceTurns(new Set());
  }, [activeSessionId]);

  useEffect(() => {
    const sessionId = activeSessionId;
    const generation = sessionSelectionGenerationRef.current;
    if (!activeSessionId) {
      setTraceTurns([]);
      setMemoryView(null);
      setSkillList(null);
      setSelectedSkill(null);
      setMcpTools(null);
      return;
    }
    if (!taskOpen) {
      return;
    }
    if (inspectorView === "trace") {
      refreshTraceTurns().catch((nextError) =>
        handleSessionRequestError(sessionId, nextError, generation),
      );
    }
    if (runtimeState?.session_id !== activeSessionId || !runtimeState.active) {
      setMemoryView(null);
      setSkillList(null);
      setSelectedSkill(null);
      setMcpTools(null);
      return;
    }
    if (inspectorView === "memory") {
      refreshMemory().catch((nextError) =>
        handleSessionRequestError(sessionId, nextError, generation),
      );
    }
    if (inspectorView === "skills") {
      refreshSkills().catch((nextError) =>
        handleSessionRequestError(sessionId, nextError, generation),
      );
    }
    if (inspectorView === "mcp") {
      refreshMcpTools().catch((nextError) =>
        handleSessionRequestError(sessionId, nextError, generation),
      );
    }
  }, [
    activeSessionId,
    handleSessionRequestError,
    inspectorView,
    refreshMemory,
    refreshTraceTurns,
    refreshSkills,
    refreshMcpTools,
    runtimeState?.active,
    runtimeState?.session_id,
    taskOpen,
  ]);

  useEffect(() => {
    let disposed = false;
    let reconnectAttempt = 0;
    let sessionUnavailable = false;
    const sessionId = activeSessionId;
    const generation = sessionSelectionGenerationRef.current;

    if (reconnectTimerRef.current !== null) {
      window.clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    socketRef.current?.close();
    clearLiveTurnState();
    if (!activeSessionId) {
      setConnectionStatus("draft");
      return;
    }
    if (activeSessionLocked) {
      setConnectionStatus("draft");
      return;
    }
    setConnectionStatus("connecting");

    const connect = (isReconnect = false) => {
      if (disposed) {
        return;
      }
      setConnectionStatus(isReconnect ? "reconnecting" : "connecting");
      const socket = openRunSocket(activeSessionId, (event) => {
        if (
          socketRef.current !== socket ||
          !isCurrentSessionSelection(sessionId, generation)
        ) {
          return;
        }
        if (event.type === "server_ready") {
          reconnectAttempt = 0;
          setConnectionStatus("ready");
          const nextRuntimeState = runtimeStateFromPayload(event.payload.runtime);
          if (nextRuntimeState) {
            applyRuntimeState(nextRuntimeState);
            if (nextRuntimeState.active) {
              markSessionActive(nextRuntimeState.session_id);
            }
            if (nextRuntimeState.running && nextRuntimeState.status === "streaming_assistant") {
              restoreStreamingMessageFromTrace(
                nextRuntimeState.session_id,
                nextRuntimeState.active_turn_id,
                generation,
              ).catch((nextError) =>
                setSessionError(sessionId, String(nextError), generation),
              );
            }
          }
          const pending = pendingFirstMessageRef.current;
          if (pending?.sessionId === activeSessionId) {
            pendingFirstMessageRef.current = null;
            finishCreatingSession();
            void runSessionMessage(pending.sessionId, pending.content);
          }
          if (isReconnect) {
            refreshActiveSession().catch((nextError) =>
              handleSessionRequestError(sessionId, nextError, generation),
            );
            refreshSessions().catch((nextError) =>
              setSessionError(sessionId, String(nextError), generation),
            );
          }
          return;
        }
        if (event.type === "server_error") {
          const code = typeof event.payload.code === "string" ? event.payload.code : "";
          if (code === "session_running" && pendingSentMessageRef.current) {
            setDraft(pendingSentMessageRef.current);
          }
          const message = String(event.payload.message ?? "Event stream error");
          if (code === "session_workspace_unavailable") {
            sessionUnavailable = true;
            setSessionError(sessionId, "", generation);
            markSessionLocked(sessionId, message);
            setConnectionStatus("draft");
            void refreshSessions().catch((nextError) =>
              setSessionError(sessionId, String(nextError), generation),
            );
          }
          const duplicatesRuntimeError =
            code === "unexpected_error" &&
            lastRuntimeErrorRef.current?.sessionId === activeSessionId &&
            lastRuntimeErrorRef.current.message === message;
          if (code !== "session_workspace_unavailable" && !duplicatesRuntimeError) {
            setSessionError(sessionId, formatServerError(event.payload), generation);
          }
          pendingFirstMessageRef.current = null;
          finishCreatingSession();
          runningSessionIdRef.current = "";
          pendingSentMessageRef.current = "";
          const currentRuntime = runtimeStateFromPayload(event.payload.runtime);
          if (currentRuntime) {
            applyRuntimeState(currentRuntime);
          } else {
            setRuntimeState(
              activeSessionId
                ? { session_id: activeSessionId, active: false, running: false, connected: true }
                : null,
            );
          }
          if (!currentRuntime?.running) {
            setBusy(false);
          }
          return;
        }
        if (event.type === "model_request") {
          setLiveRuntimeStatus("requesting_model", event.turn_id || null);
          return;
        }
        if (event.type === "model_retry") {
          const attempt = Number(event.payload.attempt ?? 0);
          const maxRetries = Number(event.payload.max_retries ?? 0);
          const detail =
            attempt > 0 && maxRetries > 0
              ? `Reconnecting... ${attempt}/${maxRetries}`
              : "Reconnecting...";
          setLiveRuntimeStatus("model_retrying", event.turn_id || null, detail);
          return;
        }
        if (event.type === "assistant_delta") {
          setLiveRuntimeStatus("streaming_assistant", event.turn_id || null);
          appendStreamingDelta(String(event.payload.delta ?? ""));
          return;
        }
        if (event.type === "approval_request") {
          const request = approvalRequestFromPayload(event.payload);
          if (request) {
            setApprovalRequest(request);
            setLiveRuntimeStatus("running_tool", event.turn_id || null);
          }
          return;
        }
        if (event.type === "review_summary") {
          window.setTimeout(() => {
            refreshTraceTurns().catch((nextError) =>
              setSessionError(sessionId, String(nextError), generation),
            );
          }, 100);
          return;
        }
        if (event.type === "assistant_message") {
          const toolCallCount = Number(event.payload.tool_call_count ?? 0);
          if (toolCallCount > 0) {
            pendingToolReasoningRef.current = String(event.payload.content ?? "").trim();
            setStreamingMessage("");
            return;
          }
          setLiveRuntimeStatus("finalizing", event.turn_id || null);
          if (!event.payload.streamed) {
            clearLiveTurnState();
            appendStreamingDelta(String(event.payload.content ?? ""));
          }
          return;
        }
        if (event.type === "tool_call" || event.type === "tool_result") {
          setLiveRuntimeStatus("running_tool", event.turn_id || null);
          const reasoning = event.type === "tool_call" ? pendingToolReasoningRef.current : "";
          const item = runtimeToolItem(event, reasoning);
          if (item) {
            setLiveToolItems((current) => [...current, item]);
            if (event.type === "tool_call") {
              pendingToolReasoningRef.current = "";
            }
          }
          return;
        }
        if (event.type === "turn_end") {
          const turnError = event.payload.error;
          if (turnError) {
            lastRuntimeErrorRef.current = {
              sessionId: activeSessionId,
              message: String(turnError),
            };
            setLiveToolItems((current) => [
              ...current,
              {
                id: `live-${event.turn_id}-error-${current.length}`,
                kind: "runtime_error",
                content: String(turnError),
                errorType:
                  typeof event.payload.error_type === "string"
                    ? event.payload.error_type
                    : null,
              },
            ]);
          }
          refreshActiveSession()
            .then(() => {
              if (!isCurrentSessionSelection(sessionId, generation)) {
                return;
              }
              clearLiveTurnState();
              runningSessionIdRef.current = "";
              pendingSentMessageRef.current = "";
              setBusy(false);
              if (activeSessionId) {
                setRuntimeState((current) => ({
                  session_id: activeSessionId,
                  active: true,
                  running: false,
                  connected: true,
                  active_turn_id: null,
                  status: null,
                  status_detail: null,
                  pending_approval: null,
                  notices: current?.session_id === activeSessionId ? current.notices : [],
                }));
              }
            })
            .catch((nextError) => {
              if (isCurrentSessionSelection(sessionId, generation)) {
                setSessionError(sessionId, String(nextError), generation);
                runningSessionIdRef.current = "";
                pendingSentMessageRef.current = "";
                setBusy(false);
              }
            });
          refreshSessions().catch((nextError) =>
            setSessionError(sessionId, String(nextError), generation),
          );
        }
      });
      socketRef.current = socket;
      socket.onclose = () => {
        if (
          socketRef.current === socket &&
          isCurrentSessionSelection(sessionId, generation)
        ) {
          if (sessionUnavailable) {
            socketRef.current = null;
            return;
          }
          if (sessionId) {
            getRuntimeState(sessionId)
              .then((nextRuntimeState) => {
                if (isCurrentSessionSelection(sessionId, generation)) {
                  applyRuntimeState({ ...nextRuntimeState, connected: false });
                }
              })
              .catch(() => {
                setRuntimeState((current) =>
                  isCurrentSessionSelection(sessionId, generation) &&
                  current &&
                  current.session_id === sessionId
                    ? { ...current, connected: false }
                    : current,
                );
              });
          }
          if (!disposed) {
            const delay = RUN_SOCKET_RECONNECT_DELAYS_MS[reconnectAttempt];
            if (delay === undefined) {
              finishCreatingSession();
              setConnectionStatus("connecting");
              setSessionError(
                sessionId,
                "Run socket disconnected. Refresh or switch sessions to reconnect.",
                generation,
              );
              return;
            }
            reconnectAttempt += 1;
            setConnectionStatus("reconnecting");
            reconnectTimerRef.current = window.setTimeout(() => {
              reconnectTimerRef.current = null;
              connect(true);
            }, delay);
          }
        }
      };
      socket.onerror = () => {
        if (
          socketRef.current === socket &&
          isCurrentSessionSelection(sessionId, generation)
        ) {
          pendingFirstMessageRef.current = null;
          finishCreatingSession();
          if (sessionId) {
            getRuntimeState(sessionId)
              .then((nextRuntimeState) => {
                if (isCurrentSessionSelection(sessionId, generation)) {
                  applyRuntimeState({ ...nextRuntimeState, connected: false });
                }
              })
              .catch(() => {
                if (isCurrentSessionSelection(sessionId, generation)) {
                  runningSessionIdRef.current = "";
                  pendingSentMessageRef.current = "";
                  setBusy(false);
                }
              });
          } else {
            runningSessionIdRef.current = "";
            pendingSentMessageRef.current = "";
            setBusy(false);
          }
        }
      };
    };
    connect();
    return () => {
      disposed = true;
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [
    activeSessionId,
    activeSessionLocked,
    appendStreamingDelta,
    applyRuntimeState,
    clearLiveTurnState,
    finishCreatingSession,
    handleSessionRequestError,
    isCurrentSessionSelection,
    markSessionActive,
    markSessionLocked,
    refreshActiveSession,
    refreshSessions,
    runSessionMessage,
    setSessionError,
  ]);

  const chatItems = useMemo(() => transcriptToChatItems(messages, inspection), [inspection, messages]);
  const visibleChatItems = useMemo(() => [...chatItems, ...liveToolItems], [chatItems, liveToolItems]);
  const groupedSessions = useMemo<SessionWorkspaceGroup[]>(() => {
    const groups = new Map<string, SessionWorkspaceGroup>();
    const orderedGroups: SessionWorkspaceGroup[] = [];
    for (const session of sessions) {
      const key = session.cwd || "__no_workspace__";
      let group = groups.get(key);
      if (!group) {
        group = {
          key,
          label: workspaceLabel(session.cwd),
          title: session.cwd || "No workspace",
          sessions: [],
        };
        groups.set(key, group);
        orderedGroups.push(group);
      }
      group.sessions.push(session);
    }
    return orderedGroups;
  }, [sessions]);
  const activeSessionWorkspaceKey = activeSession?.cwd || "__no_workspace__";
  const lastAssistantContent = useMemo(() => {
    for (let index = chatItems.length - 1; index >= 0; index -= 1) {
      const item = chatItems[index];
      if (item.kind === "assistant") {
        return item.content.trim();
      }
    }
    return "";
  }, [chatItems]);
  const showStreamingMessage =
    Boolean(streamingMessage) && streamingMessage.trim() !== lastAssistantContent;
  const currentSessionRunning = Boolean(
    activeSessionId &&
      (runtimeState?.session_id === activeSessionId
        ? runtimeState.running
        : busy && runningSessionIdRef.current === activeSessionId),
  );
  const currentSessionActive = Boolean(
    activeSessionId && runtimeState?.session_id === activeSessionId && runtimeState.active,
  );
  const currentSessionMcpReloading = Boolean(activeSessionId && mcpReloadingSessionId === activeSessionId);
  const currentSessionModelSwitching = Boolean(activeSessionId && modelSwitchingSessionId === activeSessionId);
  const runtimeNotices =
    runtimeState?.session_id === activeSessionId ? runtimeState.notices ?? [] : [];
  const selectedModelProviderView = modelProviders.find(
    (provider) => provider.name === selectedModelProvider,
  );
  const additionalModelProviders = modelProviders.filter(
    (provider) => provider.name !== selectedModelProvider,
  );
  const filteredProviderModels = useMemo(() => {
    const discoveredModels = providerModels?.models ?? [];
    const fallbackModel = selectedModelProviderView?.default_model || "";
    const models = discoveredModels.length || !fallbackModel ? discoveredModels : [fallbackModel];
    const query = modelSearch.trim().toLowerCase();
    if (!query) {
      return models;
    }
    return models.filter((model) => model.toLowerCase().includes(query));
  }, [modelSearch, providerModels?.models, selectedModelProviderView?.default_model]);
  const composerDisabled =
    creatingSession ||
    activeSessionLocked ||
    currentSessionRunning ||
    currentSessionMcpReloading ||
    currentSessionModelSwitching ||
    Boolean(activeSessionId && connectionStatus !== "ready");
  const statusLabel = !activeSessionId
    ? "Draft"
    : activeSessionLocked
      ? "Workspace unavailable"
    : connectionStatus === "reconnecting"
      ? "Reconnecting"
      : connectionStatus !== "ready"
        ? "Connecting"
        : !currentSessionActive
          ? "Chat to start"
        : approvalRequest
          ? "Waiting approval"
          : runtimeState?.status === "interrupting"
            ? "Interrupting"
          : runtimeState?.status === "requesting_model"
            ? "Requesting model"
            : runtimeState?.status === "model_retrying"
              ? runtimeState.status_detail || "Reconnecting..."
              : runtimeState?.status === "streaming_assistant"
                ? "Streaming"
                : runtimeState?.status === "running_tool"
                  ? "Running tool"
                  : runtimeState?.status === "finalizing"
                    ? "Finalizing"
                    : currentSessionRunning
                      ? "Running"
                      : "Ready";

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ block: "end" });
  }, [activeSessionId, visibleChatItems.length, showStreamingMessage, streamingMessage]);

  useEffect(() => {
    const textarea = composerTextareaRef.current;
    if (!textarea) {
      return;
    }
    textarea.style.height = "auto";
    textarea.style.height = `${textarea.scrollHeight}px`;
  }, [draft]);

  function toggleWorkspaceGroup(key: string) {
    setCollapsedWorkspaceGroups((current) => ({
      ...current,
      [key]: !current[key],
    }));
  }

  async function handleCreateSession() {
    if (creatingSessionRef.current) {
      return;
    }
    if (activeSessionIdRef.current) {
      selectSession("");
    } else {
      sessionSelectionGenerationRef.current += 1;
    }
    setInspection(null);
    setMessages([]);
    setTaskState(null);
    setRuntimeState(null);
    setMemoryView(null);
    setSkillList(null);
    setSelectedSkill(null);
    setMcpTools(null);
    clearLiveTurnState();
    pendingFirstMessageRef.current = null;
    runningSessionIdRef.current = "";
    pendingSentMessageRef.current = "";
    setBusy(false);
    setDraft("");
    setWorkspacePickerOpen(false);
    setWorkspaceBrowser(null);
    setWorkspaceBrowserError("");
    if (defaultWorkspaceRef.current) {
      setWorkspaceDraft(defaultWorkspaceRef.current);
      return;
    }
    try {
      const workspace = await browseWorkspace();
      defaultWorkspaceRef.current = workspace.path;
      setWorkspaceDraft(workspace.path);
    } catch (nextError) {
      setError(String(nextError));
    }
  }

  function handleSelectSession(sessionId: string) {
    if (!creatingSessionRef.current) {
      selectSession(sessionId);
    }
  }

  async function handleDeleteSession(sessionId: string) {
    if (creatingSessionRef.current) {
      return;
    }
    if (!window.confirm("Delete this session?")) {
      return;
    }
    setError("");
    try {
      await deleteSession(sessionId);
      const nextSessions = sessions.filter((session) => session.session_id !== sessionId);
      setSessions((current) =>
        current.filter((session) => session.session_id !== sessionId),
      );
      if (activeSessionIdRef.current === sessionId) {
        selectSession(nextSessions[0]?.session_id ?? "");
      }
    } catch (nextError) {
      setError(String(nextError));
    }
  }

  async function handleRecheckWorkspace() {
    setError("");
    try {
      await refreshSessions();
    } catch (nextError) {
      setError(String(nextError));
    }
  }

  async function submitMessage() {
    const content = draft.trim();
    if (!content || composerDisabled || creatingSessionRef.current) {
      return;
    }
    if (!activeSessionId && selectedModelProvider && modelDraft.trim()) {
      const provider = modelProviders.find((item) => item.name === selectedModelProvider);
      if (!modelProviderReady(provider)) {
        setError(`Model provider '${selectedModelProvider}' requires ${modelProviderMissingFields(provider)}.`);
        return;
      }
    }
    const creatingDraftSession = !activeSessionId;
    let firstMessagePending = false;
    if (creatingDraftSession) {
      creatingSessionRef.current = true;
      setCreatingSession(true);
      setModelPanelOpen(false);
    }
    setDraft("");
    pendingSentMessageRef.current = content;
    setBusy(true);
    setError("");
    lastRuntimeErrorRef.current = null;
    clearLiveTurnState();
    setMessages((current) => [...current, { role: "user", content }]);
    try {
      if (!activeSessionId) {
        const session = await createSession(workspaceDraft.trim() || undefined);
        if (selectedModelProvider && modelDraft.trim()) {
          await updateSessionModel(session.session_id, selectedModelProvider, modelDraft.trim());
        }
        runningSessionIdRef.current = session.session_id;
        setRuntimeState({
          session_id: session.session_id,
          active: true,
          running: true,
          connected: false,
          notices: [],
        });
        pendingFirstMessageRef.current = {
          sessionId: session.session_id,
          content,
        };
        firstMessagePending = true;
        selectSession(session.session_id);
        setSessions((current) => [session, ...current]);
        return;
      }
      runningSessionIdRef.current = activeSessionId;
      runSessionMessage(activeSessionId, content);
    } catch (nextError) {
      setError(String(nextError));
      runningSessionIdRef.current = "";
      pendingSentMessageRef.current = "";
      setBusy(false);
    } finally {
      if (creatingDraftSession && !firstMessagePending) {
        finishCreatingSession();
      }
    }
  }

  function respondToApproval(approved: boolean) {
    if (!approvalRequest || !socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) {
      return;
    }
    socketRef.current.send(
      JSON.stringify({
        type: "approval_response",
        request_id: approvalRequest.request_id,
        approved,
      }),
    );
    setApprovalRequest(null);
  }

  function interruptTurn() {
    if (!activeSessionId || !socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) {
      return;
    }
    socketRef.current.send(JSON.stringify({ type: "interrupt" }));
    setApprovalRequest(null);
    setRuntimeState((current) => ({
      session_id: activeSessionId,
      active: true,
      running: true,
      connected: true,
      active_turn_id: current?.session_id === activeSessionId ? current.active_turn_id ?? null : null,
      status: "interrupting",
      status_detail: null,
      pending_approval: null,
      notices: current?.session_id === activeSessionId ? current.notices : [],
    }));
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    await submitMessage();
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    const nativeEvent = event.nativeEvent;
    if (
      event.key !== "Enter" ||
      event.shiftKey ||
      nativeEvent.isComposing ||
      nativeEvent.keyCode === 229
    ) {
      return;
    }
    event.preventDefault();
    void submitMessage();
  }

  return (
    <main
      className={`app-shell ${sessionsOpen ? "sessions-open" : "sessions-collapsed"} ${
        taskOpen ? "task-open" : "task-collapsed"
      }`}
      style={{ "--inspector-width": `${inspectorWidth}px` } as CSSProperties}
    >
      <aside className={`sidebar ${sessionsOpen ? "expanded" : "collapsed"}`}>
        {sessionsOpen ? (
          <>
            <div className="brand-row">
              <div>
                <h1>lulu-agent</h1>
                <p>Local runtime</p>
              </div>
              <div className="toolbar-actions">
                <button className="icon-button" type="button" onClick={refreshSessions} title="Refresh sessions">
                  <RefreshCcw size={17} />
                </button>
                <button
                  className="icon-button"
                  type="button"
                  onClick={() => setSessionsOpen(false)}
                  title="Collapse sessions"
                >
                  <PanelLeftClose size={17} />
                </button>
              </div>
            </div>
            <button
              className="primary-button"
              type="button"
              onClick={handleCreateSession}
              disabled={creatingSession}
            >
              <MessageSquarePlus size={17} />
              New session
            </button>
            <div className="session-list">
              {groupedSessions.map((group) => {
                const collapsed = Boolean(collapsedWorkspaceGroups[group.key]);
                const activeGroup = group.key === activeSessionWorkspaceKey;
                return (
                  <section className={`session-workspace-group ${activeGroup ? "active" : ""}`} key={group.key}>
                    <button
                      className="session-workspace-toggle"
                      type="button"
                      onClick={() => toggleWorkspaceGroup(group.key)}
                      title={group.title}
                      aria-expanded={!collapsed}
                    >
                      {collapsed ? <ChevronRight size={15} /> : <ChevronDown size={15} />}
                      <Folder size={15} />
                      <span>{group.label}</span>
                      <small>{group.sessions.length}</small>
                    </button>
                    {!collapsed && (
                      <div className="session-workspace-items">
                        {group.sessions.map((session) => (
                          <div
                            className={`session-item ${session.session_id === activeSessionId ? "active" : ""} ${session.locked ? "locked" : ""}`}
                            key={session.session_id}
                          >
                            <button
                              className="session-select"
                              type="button"
                              onClick={() => handleSelectSession(session.session_id)}
                              disabled={creatingSession}
                            >
                              <span className="session-title">
                                {session.locked ? (
                                  <span title={session.lock_message || "Workspace unavailable"}>
                                    <LockKeyhole size={14} />
                                  </span>
                                ) : session.active ? (
                                  <span className="session-active-dot" title="Agent loaded" />
                                ) : null}
                                <span>{session.title || "(untitled)"}</span>
                              </span>
                              <small>{session.locked ? "Workspace unavailable" : `Updated at: ${formatDate(session.updated_at)}`}</small>
                            </button>
                            <button
                              className="session-delete"
                              type="button"
                              onClick={() => void handleDeleteSession(session.session_id)}
                              title="Delete session"
                              disabled={creatingSession}
                            >
                              <Trash2 size={15} />
                            </button>
                          </div>
                        ))}
                      </div>
                    )}
                  </section>
                );
              })}
            </div>
          </>
        ) : (
          <button
            className="panel-rail-button"
            type="button"
            onClick={() => setSessionsOpen(true)}
            title="Open sessions"
          >
            <PanelLeftOpen size={18} />
          </button>
        )}
      </aside>

      <section className="main-panel">
        <header className="topbar">
          <div>
            <div className="topbar-title-row">
              <h2>{activeSession?.title || "New session"}</h2>
              {activeSession?.created_at && (
                <span>Created at: {formatTraceTimestamp(activeSession.created_at)}</span>
              )}
            </div>
            {!activeSession?.created_at && <p>Session will be created on first message</p>}
            {!activeSession?.created_at && (
              <div className="workspace-summary">
                <span>Selected workspace</span>
                <div className="workspace-summary-row">
                  <p title={workspaceDraft || "Not selected"}>{workspaceDraft || "Not selected"}</p>
                  <button
                    className="secondary-button"
                    type="button"
                    onClick={() => {
                      setWorkspacePickerOpen(true);
                      void loadWorkspaceBrowser(workspaceDraft.trim() || undefined);
                    }}
                    disabled={busy || creatingSession}
                  >
                    <Folder size={15} />
                    Browse
                  </button>
                </div>
              </div>
            )}
          </div>
        </header>

        {activeSessionLocked && (
          <div className="workspace-lock-banner">
            <LockKeyhole size={18} />
            <div>
              <strong>Workspace unavailable</strong>
              <p>{activeSession?.lock_message || "Check the filesystem and try again."}</p>
            </div>
            <button className="secondary-button" type="button" onClick={() => void handleRecheckWorkspace()}>
              <RefreshCcw size={15} />
              Recheck
            </button>
          </div>
        )}

        {error && (
          <div className="error-banner">
            <AlertCircle size={16} />
            {error}
          </div>
        )}

        {approvalRequest && (
          <div className="approval-banner">
            <div className="approval-actions">
              <button className="approval-deny" type="button" onClick={() => respondToApproval(false)}>
                Deny
              </button>
              <button className="approval-allow" type="button" onClick={() => respondToApproval(true)}>
                Approve
              </button>
            </div>
            <div>
              <strong>Approval required</strong>
              <p>{approvalRequest.reason}</p>
              <code>{approvalRequest.subject}</code>
            </div>
          </div>
        )}

        <div className="chat-list">
          {visibleChatItems.map((item) => (
            <article className={`chat-message ${item.kind}`} key={item.id}>
              <div className="message-role">
                {item.kind === "runtime_error" ? "runtime" : item.kind.replace("_", " ")}
                {item.kind === "runtime_error" && item.errorType && (
                  <span className="error-type-pill">{item.errorType}</span>
                )}
              </div>
              {item.kind === "tool_call" || item.kind === "tool_result" ? (
                (() => {
                  const reasoning = item.kind === "tool_call" ? item.assistantContent.trim() : "";
                  return (
                <>
                  <button
                    className="event-toggle"
                    type="button"
                    onClick={() =>
                      setExpandedMessages((current) => {
                        const next = new Set(current);
                        if (next.has(item.id)) {
                          next.delete(item.id);
                        } else {
                          next.add(item.id);
                        }
                        return next;
                      })
                    }
                  >
                    <Bot size={15} />
                    <span>{item.title}</span>
                    <small>{expandedMessages.has(item.id) ? "Collapse" : "Expand details"}</small>
                  </button>
                  {expandedMessages.has(item.id) && (
                    <div className="tool-detail">
                      {item.kind === "tool_call" && reasoning && (
                        <div className="tool-assistant-content">
                          <strong>Reasoning</strong>
                          <p>{reasoning}</p>
                        </div>
                      )}
                      <pre className="tool-result">
                        {item.kind === "tool_call"
                          ? formatDetails(item.toolCalls)
                          : formatDetails(item.toolResult)}
                      </pre>
                    </div>
                  )}
                </>
                  );
                })()
              ) : item.kind === "assistant" ? (
                <MarkdownContent content={item.content || "[empty]"} />
              ) : (
                <p>{item.content || "[empty]"}</p>
              )}
            </article>
          ))}
          {showStreamingMessage && (
            <article className="chat-message assistant streaming">
              <div className="message-role">assistant</div>
              <p>{streamingMessage}</p>
            </article>
          )}
          <div ref={chatEndRef} />
        </div>

        <form className="composer" onSubmit={handleSubmit}>
          <div className="composer-box">
            <textarea
              ref={composerTextareaRef}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={handleComposerKeyDown}
              placeholder="Ask lulu-agent..."
              rows={2}
              disabled={composerDisabled}
            />
            <div className="composer-meta">
              <div className="runtime-status">
                {runtimeNotices.length > 0 && (
                  <span className="notice-indicator" aria-label={runtimeNotices.join("\n")}>
                    !
                    <span className="notice-tooltip" role="tooltip">
                      {runtimeNotices.map((notice, index) => (
                        <span key={`notice-${index}`}>{notice}</span>
                      ))}
                    </span>
                  </span>
                )}
                <div className="status-pill">
                  <Activity size={15} />
                  {statusLabel}
                </div>
              </div>
              <div className="model-config-control">
                <button
                  ref={modelConfigButtonRef}
                  className={`model-config-pill ${modelConfig?.model ? "" : "unavailable"}`}
                  type="button"
                  title="Model configuration"
                  disabled={activeSessionLocked}
                  onClick={() => {
                    updateModelPanelPosition();
                    setModelPanelOpen((current) => !current);
                  }}
                >
                  <span>{modelConfig?.model || "Model unavailable"}</span>
                  {modelConfig?.base_url_host && <small>{modelConfig.base_url_host}</small>}
                </button>
                {modelPanelOpen && (
                  <div className="model-switch-panel" style={modelPanelStyle}>
                    <div className="model-switch-field">
                      <span>Provider</span>
                      <button
                        className="provider-selected-option"
                        type="button"
                        onClick={() => setProviderListOpen((current) => !current)}
                      >
                        <span>{selectedModelProviderView?.name || "No provider selected"}</span>
                        <small>{selectedModelProviderView?.base_url_host || ""}</small>
                        {providerListOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                      </button>
                      {providerListOpen && (
                        <div className="provider-list">
                          {additionalModelProviders.length ? (
                            additionalModelProviders.map((provider) => (
                              <button
                                className="provider-option"
                                disabled={!modelProviderReady(provider)}
                                key={provider.name}
                                title={!modelProviderReady(provider) ? modelProviderMissingLabel(provider) : undefined}
                                type="button"
                                onClick={() => {
                                  setSelectedModelProvider(provider.name);
                                  setProviderModels(null);
                                  setModelDraft(provider.default_model || "");
                                  setProviderListOpen(false);
                                  setModelListOpen(false);
                                  setModelSearch("");
                                  refreshProviderModels(provider.name, provider.default_model).catch((nextError) =>
                                    setError(String(nextError)),
                                  );
                                }}
                              >
                                <span>{provider.name}</span>
                                <small>
                                  {modelProviderMissingLabel(provider)}
                                </small>
                              </button>
                            ))
                          ) : (
                            <small>No additional providers configured</small>
                          )}
                        </div>
                      )}
                    </div>
                    <div className="model-switch-field">
                      <span>Model</span>
                      <button
                        className="model-selected-option"
                        disabled={modelListLoading || !modelProviderReady(selectedModelProviderView)}
                        type="button"
                        onClick={() => setModelListOpen((current) => !current)}
                      >
                        <span>{modelDraft || "No model selected"}</span>
                        {modelListOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                      </button>
                      {modelListOpen && (
                        <>
                          <input
                            className="model-search-input"
                            value={modelSearch}
                            onChange={(event) => setModelSearch(event.target.value)}
                            placeholder="Search models..."
                          />
                          <div className="model-option-list">
                            {filteredProviderModels.length ? (
                              filteredProviderModels.map((model) => (
                                <button
                                  className={`model-option ${model === modelDraft ? "active" : ""}`}
                                  disabled={modelListLoading || !modelProviderReady(selectedModelProviderView)}
                                  key={model}
                                  type="button"
                                  onClick={() => {
                                    setModelDraft(model);
                                    setModelListOpen(false);
                                    setModelSearch("");
                                  }}
                                >
                                  <span>{model}</span>
                                </button>
                              ))
                            ) : (
                              <small>
                                {modelListLoading
                                  ? "Loading models..."
                                  : (providerModels?.models ?? []).length ||
                                      selectedModelProviderView?.default_model
                                    ? "No matching models"
                                    : "No models discovered"}
                              </small>
                            )}
                          </div>
                        </>
                      )}
                    </div>
                    {providerModels?.error && <small>{providerModels.error}</small>}
                    <div className="model-switch-actions">
                      <button
                        className="text-button"
                        type="button"
                        onClick={() =>
                          selectedModelProvider &&
                          refreshProviderModels(selectedModelProvider, selectedModelProviderView?.default_model).catch((nextError) => setError(String(nextError)))
                        }
                      >
                        Refresh
                      </button>
                      <button
                        className="text-button"
                        type="button"
                        disabled={
                          currentSessionRunning ||
                          currentSessionMcpReloading ||
                          currentSessionModelSwitching ||
                          modelListLoading ||
                          !selectedModelProvider ||
                          !modelProviderReady(selectedModelProviderView) ||
                          !modelDraft.trim()
                        }
                        onClick={() => applyModelSelection().catch((nextError) => setError(String(nextError)))}
                      >
                        {currentSessionModelSwitching ? "Applying" : "Apply"}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
            {currentSessionRunning ? (
              <button
                className="send-button"
                disabled={!activeSessionId || connectionStatus !== "ready"}
                title="Interrupt current turn"
                type="button"
                onClick={interruptTurn}
              >
                <Square size={17} />
              </button>
            ) : (
              <button
                className="send-button"
                disabled={!draft.trim() || composerDisabled}
                type="submit"
              >
                <Send size={18} />
              </button>
            )}
          </div>
        </form>
      </section>

      <aside className={`inspector ${taskOpen ? "expanded" : "collapsed"}`}>
        {taskOpen ? (
          <>
            <div
              className="inspector-resizer"
              onPointerDown={startInspectorResize}
              onPointerMove={resizeInspector}
              role="separator"
              aria-label="Resize inspector"
              aria-orientation="vertical"
            />
            <section className="panel-section">
            <div className="section-title">
            <div className="inspector-tabs">
                <button
                  className={`inspector-tab ${inspectorView === "trace" ? "active" : ""}`}
                  type="button"
                  onClick={() => setInspectorView("trace")}
                  title="Trace"
                >
                  <History size={16} />
                  <span>Trace</span>
                </button>
                <button
                  className={`inspector-tab ${inspectorView === "task" ? "active" : ""}`}
                  type="button"
                  onClick={() => setInspectorView("task")}
                  title="Task"
                >
                  <ListTree size={16} />
                  <span>Task</span>
                </button>
                <button
                  className={`inspector-tab ${inspectorView === "memory" ? "active" : ""}`}
                  type="button"
                  onClick={() => setInspectorView("memory")}
                  title="Memory"
                >
                  <Brain size={16} />
                  <span>Memory</span>
                </button>
                <button
                  className={`inspector-tab ${inspectorView === "skills" ? "active" : ""}`}
                  type="button"
                  onClick={() => setInspectorView("skills")}
                  title="Skills"
                >
                  <BookOpen size={16} />
                  <span>Skills</span>
                </button>
                <button
                  className={`inspector-tab ${inspectorView === "mcp" ? "active" : ""}`}
                  type="button"
                  onClick={() => setInspectorView("mcp")}
                  title="MCP"
                >
                  <Wrench size={16} />
                  <span>MCP</span>
                </button>
              </div>
              <button
                className="icon-button"
                type="button"
                onClick={() => setTaskOpen(false)}
                title="Collapse task"
              >
                <PanelRightClose size={17} />
              </button>
            </div>
            {inspectorView === "trace" ? (
              <div className="trace-block">
                <div className="knowledge-header">
                  <strong>Trace</strong>
                  <button className="text-button" type="button" onClick={() => void refreshTraceTurns()}>
                    <RefreshCcw size={14} />
                    Refresh
                  </button>
                </div>
                {activeSessionLocked ? (
                  <p className="muted">Workspace unavailable. Recheck the session before viewing trace.</p>
                ) : !activeSessionId ? (
                  <p className="muted">Chat with lulu in this session to load trace.</p>
                ) : traceTurns.length > 0 ? (
                  <div className="trace-list">
                    {traceTurns.map((turn) => {
                      const expanded = expandedTraceTurns.has(turn.turn_id);
                      const turnStatusClass = traceTurnStatusClass(turn);
                      const reviewBadge = traceReviewBadge(turn);
                      return (
                        <section className={`trace-turn ${turnStatusClass}`} key={turn.turn_id}>
                          <button
                            className="trace-turn-toggle"
                            type="button"
                            aria-expanded={expanded}
                            onClick={() =>
                              setExpandedTraceTurns((current) => {
                                const next = new Set(current);
                                if (next.has(turn.turn_id)) {
                                  next.delete(turn.turn_id);
                                } else {
                                  next.add(turn.turn_id);
                                }
                                return next;
                              })
                            }
                          >
                            {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                            <strong>{turn.turn_id}</strong>
                            <span className={`trace-status ${turnStatusClass}`}>{turn.status || "running"}</span>
                            {reviewBadge && (
                              <span
                                className={`trace-review-badge ${reviewBadge.className}`}
                                title={reviewBadge.title}
                              >
                                {reviewBadge.label}
                              </span>
                            )}
                            {turn.error_type && <span className="trace-error-type">{turn.error_type}</span>}
                            <small>{turn.event_count} events</small>
                          </button>
                          {expanded && (
                            <div className="trace-turn-body">
                              <div className="trace-turn-counts">
                                <span>model {turn.model_request_count}</span>
                                <span>retry {turn.model_retry_count}</span>
                                <span>text chunk {turn.assistant_delta_count}</span>
                                <span>tool call {turn.tool_call_count}</span>
                                <span>tool result {turn.tool_result_count}</span>
                              </div>
                              <div className="trace-timeline">
                                {turn.items.map((item, index) => {
                                  const itemError = tracePayloadValue(item, "error");
                                  const itemErrorType = tracePayloadValue(item, "error_type");
                                  const itemErrorText = itemError ? String(itemError) : "";
                                  const itemErrorTypeText = itemErrorType ? String(itemErrorType) : "";
                                  const showItemError =
                                    item.event_type !== "turn_end" &&
                                    item.event_type !== "model_retry" &&
                                    item.event_type !== "tool_result" &&
                                    Boolean(itemErrorText || itemErrorTypeText);
                                  const detailFields = traceDetailFields(item);
                                  const detailText = traceDetailText(item);
                                  return (
                                    <article className="trace-item" key={`${turn.turn_id}-${index}-${item.event_type}`}>
                                      <div className="trace-item-head">
                                        <strong>{item.label || item.event_type || "event"}</strong>
                                        {item.timestamp && <small>{formatTraceTimestamp(item.timestamp)}</small>}
                                      </div>
                                      {detailFields.length > 0 && (
                                        <div className="trace-detail-fields">
                                          {detailFields.map((field) => (
                                            <span key={field.label} className={traceDetailFieldClass(field)}>
                                              <strong>{field.label}</strong>
                                              {field.value}
                                            </span>
                                          ))}
                                        </div>
                                      )}
                                      {detailText && <p className="trace-item-detail">{detailText}</p>}
                                      {showItemError && (
                                        <div className="trace-item-error">
                                          {itemErrorTypeText && <span className="error-type-pill">{itemErrorTypeText}</span>}
                                          {itemErrorText && <span>{itemErrorText}</span>}
                                        </div>
                                      )}
                                    </article>
                                  );
                                })}
                              </div>
                            </div>
                          )}
                        </section>
                      );
                    })}
                  </div>
                ) : (
                  <p className="muted">No trace recorded.</p>
                )}
              </div>
            ) : inspectorView === "task" ? (
              <div className="knowledge-block">
                <div className="knowledge-header">
                  <strong>Task</strong>
                  <button className="text-button" type="button" onClick={() => void refreshTask()}>
                    <RefreshCcw size={14} />
                    Refresh
                  </button>
                </div>
                {!currentSessionActive ? (
                  <p className="muted">Chat with lulu in this session to load task state.</p>
                ) : taskState ? (
                  <div className="task-block">
                    <strong>{taskState.goal}</strong>
                    <span className="status-chip">{taskState.status}</span>
                    <ol>
                      {taskState.steps.map((step) => (
                        <li key={step.id}>
                          <span>{step.step}</span>
                          <small>{step.status}</small>
                        </li>
                      ))}
                    </ol>
                    {taskState.next_action && <p className="next-action">{taskState.next_action}</p>}
                  </div>
                ) : (
                  <p className="muted">No task state.</p>
                )}
              </div>
            ) : inspectorView === "memory" ? (
              <div className="knowledge-block">
                <div className="knowledge-header">
                  <strong>Memory</strong>
                  <button className="text-button" type="button" onClick={() => void refreshMemory()}>
                    <RefreshCcw size={14} />
                    Refresh
                  </button>
                </div>
                {!currentSessionActive ? (
                  <p className="muted">Chat with lulu in this session to load memory.</p>
                ) : memoryView ? (
                  <>
                    <small>{memoryView.path}</small>
                    <pre className="knowledge-content">{memoryView.content || "[empty]"}</pre>
                  </>
                ) : (
                  <p className="muted">No memory loaded.</p>
                )}
              </div>
            ) : inspectorView === "skills" ? (
              <div className="knowledge-block">
                <div className="knowledge-header">
                  <strong>Skills</strong>
                  <button className="text-button" type="button" onClick={() => void refreshSkills()}>
                    <RefreshCcw size={14} />
                    Refresh
                  </button>
                </div>
                {!currentSessionActive ? (
                  <p className="muted">Chat with lulu in this session to load skills.</p>
                ) : skillList ? (
                  <>
                    <small>{skillList.root}</small>
                    <div className="skill-browser">
                      <div className="skill-list">
                        {skillList.skills.map((skill) => (
                          <button
                            className={`skill-item ${selectedSkill?.name === skill.name ? "active" : ""}`}
                            key={skill.name}
                            type="button"
                            onClick={() => void loadSkill(skill.name)}
                          >
                            <strong>{skill.name}</strong>
                            <span>{skill.description}</span>
                          </button>
                        ))}
                      </div>
                      {selectedSkill ? (
                        <div className="skill-document">
                          <div>
                            <strong>{selectedSkill.name}</strong>
                            <span>{selectedSkill.description}</span>
                          </div>
                          <pre className="skill-content">{selectedSkill.content || "[empty]"}</pre>
                        </div>
                      ) : (
                        <p className="skill-placeholder muted">Select a skill to read.</p>
                      )}
                    </div>
                    {skillList.load_issues.length > 0 && (
                      <pre className="knowledge-content">{formatDetails(skillList.load_issues)}</pre>
                    )}
                  </>
                ) : (
                  <p className="muted">No skills loaded.</p>
                )}
              </div>
            ) : inspectorView === "mcp" ? (
              <div className="knowledge-block">
                <div className="knowledge-header">
                  <strong>MCP</strong>
                  <button
                    className="text-button"
                    type="button"
                    disabled={
                      !currentSessionActive ||
                      currentSessionRunning ||
                      currentSessionMcpReloading
                    }
                    onClick={() =>
                      reloadMcpToolsForActiveSession().catch((nextError) => setError(String(nextError)))
                    }
                  >
                    <RefreshCcw size={14} />
                    {currentSessionMcpReloading ? "Reloading" : "Reload"}
                  </button>
                </div>
                {!currentSessionActive ? (
                  <p className="muted">Chat with lulu in this session to load mcp tools.</p>
                ) : mcpTools ? (
                  mcpTools.servers.length > 0 ? (
                    <div className="mcp-browser">
                      {mcpTools.servers.map((server) => (
                        <section className="mcp-server-group" key={server.name}>
                          <button
                            className="mcp-server-toggle"
                            type="button"
                            onClick={() => toggleMcpServer(server.name)}
                            aria-expanded={expandedMcpServers.has(server.name)}
                          >
                            {expandedMcpServers.has(server.name) ? (
                              <ChevronDown size={15} />
                            ) : (
                              <ChevronRight size={15} />
                            )}
                            <strong>{server.name}</strong>
                            {server.safety_profile && <span className="status-chip">{server.safety_profile}</span>}
                            <small>{server.tools.length}</small>
                          </button>
                          {expandedMcpServers.has(server.name) && (
                            <div className="mcp-tool-list">
                              {server.tools.map((tool) => (
                                <article className="mcp-tool-item" key={tool.name}>
                                  <div className="mcp-tool-head">
                                    <strong>{tool.name}</strong>
                                  </div>
                                  <p>{tool.description || "[no description]"}</p>
                                </article>
                              ))}
                            </div>
                          )}
                        </section>
                      ))}
                    </div>
                  ) : (
                    <p className="muted">No MCP tools loaded.</p>
                  )
                ) : (
                  <p className="muted">No MCP tools loaded.</p>
                )}
              </div>
            ) : null}
            </section>
          </>
        ) : (
          <button
            className="panel-rail-button"
            type="button"
            onClick={() => setTaskOpen(true)}
            title="Open task"
          >
            <PanelRightOpen size={18} />
          </button>
        )}
      </aside>

      {workspacePickerOpen && (
        <div className="workspace-modal-backdrop" role="presentation" onClick={closeWorkspacePicker}>
          <div className="workspace-modal" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
            <div className="workspace-modal-header">
              <div>
                <h3>Select workspace</h3>
                <p>Choose a directory before creating the session.</p>
              </div>
              <button className="icon-button" type="button" onClick={closeWorkspacePicker} title="Close">
                <X size={17} />
              </button>
            </div>
            <div className="workspace-modal-path">
              <div>
                <span>Current</span>
                <strong title={workspaceBrowser?.path || ""}>{workspaceBrowser?.path || "-"}</strong>
              </div>
              <button
                className="secondary-button"
                type="button"
                onClick={() => void loadWorkspaceBrowser(workspaceBrowser?.parent || undefined)}
                disabled={!workspaceBrowser?.parent || workspaceBrowserLoading}
              >
                <ArrowUp size={15} />
                Up
              </button>
            </div>
            {workspaceBrowserError && <div className="workspace-modal-error">{workspaceBrowserError}</div>}
            <div className="workspace-browser-list">
              {workspaceBrowserLoading && <div className="workspace-browser-empty">Loading...</div>}
              {!workspaceBrowserLoading && workspaceBrowser?.entries.length === 0 && (
                <div className="workspace-browser-empty">No child directories</div>
              )}
              {!workspaceBrowserLoading &&
                workspaceBrowser?.entries.map((entry) => (
                  <button
                    className="workspace-entry"
                    key={entry.path}
                    type="button"
                    onClick={() => void loadWorkspaceBrowser(entry.path)}
                  >
                    <Folder size={16} />
                    <span>{entry.name}</span>
                    <ChevronRight size={16} />
                  </button>
                ))}
            </div>
            <div className="workspace-modal-actions">
              <button className="secondary-button" type="button" onClick={closeWorkspacePicker}>
                Cancel
              </button>
              <button
                className="primary-button"
                type="button"
                onClick={() => {
                  if (workspaceBrowser?.path) {
                    setWorkspaceDraft(workspaceBrowser.path);
                    closeWorkspacePicker();
                  }
                }}
                disabled={!workspaceBrowser?.path || workspaceBrowserLoading}
              >
                <Check size={17} />
                Use this directory
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
