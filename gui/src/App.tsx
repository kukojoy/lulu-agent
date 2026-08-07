import {
  Activity,
  AlertCircle,
  Bot,
  BookOpen,
  Brain,
  ChevronDown,
  ChevronRight,
  ListTree,
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
} from "lucide-react";
import { FormEvent, KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, PointerEvent as ReactPointerEvent, ReactNode } from "react";

import {
  createSession,
  deleteSession,
  getMemory,
  getModelConfig,
  getRuntimeState,
  getTaskState,
  getTraceTimeline,
  listMcpTools,
  inspectSession,
  listSkills,
  listSessions,
  loadMessages,
  openRunSocket,
  readSkill,
} from "./api";
import type {
  ApprovalRequestView,
  ChatItem,
  MemoryView,
  McpToolsView,
  ModelConfigView,
  RuntimeState,
  SkillDocument,
  SkillListView,
  SessionInspection,
  SessionSummary,
  TaskState,
  ToolCallView,
  TranscriptMessage,
} from "./types";

type InspectorView = "task" | "memory" | "skills" | "mcp";
type ConnectionStatus = "draft" | "connecting" | "ready" | "reconnecting";

const RUN_SOCKET_RECONNECT_DELAYS_MS = [500, 1000, 2000, 4000];

function shortSessionId(sessionId: string): string {
  return sessionId.replace(/^session-/, "");
}

function formatDetails(value: unknown): string {
  return JSON.stringify(value, null, 2);
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
  if (code === "config_error") {
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
  const [runtimeState, setRuntimeState] = useState<RuntimeState | null>(null);
  const [modelConfig, setModelConfig] = useState<ModelConfigView | null>(null);
  const [memoryView, setMemoryView] = useState<MemoryView | null>(null);
  const [mcpTools, setMcpTools] = useState<McpToolsView | null>(null);
  const [skillList, setSkillList] = useState<SkillListView | null>(null);
  const [selectedSkill, setSelectedSkill] = useState<SkillDocument | null>(null);
  const [liveToolItems, setLiveToolItems] = useState<ChatItem[]>([]);
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const [taskOpen, setTaskOpen] = useState(false);
  const [inspectorWidth, setInspectorWidth] = useState(560);
  const [inspectorView, setInspectorView] = useState<InspectorView>("task");
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("draft");
  const [streamingMessage, setStreamingMessage] = useState("");
  const [approvalRequest, setApprovalRequest] = useState<ApprovalRequestView | null>(null);
  const [expandedMessages, setExpandedMessages] = useState<Set<string>>(new Set());
  const [expandedMcpServers, setExpandedMcpServers] = useState<Set<string>>(new Set());
  const socketRef = useRef<WebSocket | null>(null);
  const chatEndRef = useRef<HTMLDivElement | null>(null);
  const composerTextareaRef = useRef<HTMLTextAreaElement | null>(null);
  const pendingFirstMessageRef = useRef<{ sessionId: string; content: string } | null>(null);
  const runningSessionIdRef = useRef("");
  const pendingSentMessageRef = useRef("");
  const pendingToolReasoningRef = useRef("");
  const reconnectTimerRef = useRef<number | null>(null);
  const inspectorResizeRef = useRef({ startX: 0, startWidth: 0 });

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

  const refreshSessions = useCallback(async () => {
    const nextSessions = await listSessions();
    setSessions(nextSessions);
  }, []);

  const restoreStreamingMessageFromTrace = useCallback(
    async (sessionId: string, turnId: string | null | undefined) => {
      if (!turnId) {
        return;
      }
      const timeline = await getTraceTimeline(sessionId, turnId);
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
    [],
  );

  const refreshSession = useCallback(
    async (sessionId: string) => {
      const [nextInspection, nextMessages, nextTaskState, nextRuntimeState] = await Promise.all([
        inspectSession(sessionId),
        loadMessages(sessionId),
        getTaskState(sessionId),
        getRuntimeState(sessionId),
      ]);
      setInspection(nextInspection);
      setMessages(nextMessages);
      setTaskState(nextTaskState);
      applyRuntimeState(nextRuntimeState);
      if (!nextRuntimeState.active) {
        setMemoryView(null);
        setSkillList(null);
        setSelectedSkill(null);
        setMcpTools(null);
      }
      if (nextRuntimeState.running && nextRuntimeState.status === "streaming_assistant") {
        await restoreStreamingMessageFromTrace(sessionId, nextRuntimeState.active_turn_id);
      }
    },
    [applyRuntimeState, restoreStreamingMessageFromTrace],
  );

  const refreshActiveSession = useCallback(async () => {
    if (!activeSessionId) {
      setInspection(null);
      setMessages([]);
      setTaskState(null);
      setRuntimeState(null);
      setLiveToolItems([]);
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
  }, [activeSessionId, refreshSession]);

  const refreshMemory = useCallback(async () => {
    if (!activeSessionId || runtimeState?.session_id !== activeSessionId || !runtimeState.active) {
      setMemoryView(null);
      return;
    }
    setMemoryView(await getMemory());
  }, [activeSessionId, runtimeState?.active, runtimeState?.session_id]);

  const refreshSkills = useCallback(async () => {
    if (!activeSessionId || runtimeState?.session_id !== activeSessionId || !runtimeState.active) {
      setSkillList(null);
      setSelectedSkill(null);
      return;
    }
    const nextSkillList = await listSkills();
    setSkillList(nextSkillList);
  }, [activeSessionId, runtimeState?.active, runtimeState?.session_id]);

  const refreshMcpTools = useCallback(async () => {
    if (!activeSessionId || runtimeState?.session_id !== activeSessionId || !runtimeState.active) {
      setMcpTools(null);
      return;
    }
    setMcpTools(await listMcpTools(activeSessionId));
  }, [activeSessionId, runtimeState?.active, runtimeState?.session_id]);

  const loadSkill = useCallback(async (name: string) => {
    if (!activeSessionId || runtimeState?.session_id !== activeSessionId || !runtimeState.active) {
      return;
    }
    setSelectedSkill(await readSkill(name));
  }, [activeSessionId, runtimeState?.active, runtimeState?.session_id]);

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

  const setLiveRuntimeStatus = useCallback(
    (status: string, turnId: string | null = null) => {
      if (!activeSessionId) {
        return;
      }
      runningSessionIdRef.current = activeSessionId;
      setBusy(true);
      setRuntimeState((current) => ({
        session_id: activeSessionId,
        active: true,
        running: true,
        connected: true,
        active_turn_id: turnId ?? (current?.session_id === activeSessionId ? current.active_turn_id ?? null : null),
        status,
        pending_approval: current?.session_id === activeSessionId ? current.pending_approval ?? null : null,
        notices: current?.session_id === activeSessionId ? current.notices : [],
      }));
    },
    [activeSessionId],
  );

  const runSessionMessage = useCallback(
    (sessionId: string, content: string) => {
      if (!socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) {
        setError("Run socket is not ready.");
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
        pending_approval: null,
        notices: current?.session_id === sessionId ? current.notices : [],
      }));
      socketRef.current.send(JSON.stringify({ type: "user_message", content }));
    },
    [clearLiveTurnState],
  );

  useEffect(() => {
    refreshSessions().catch((nextError) => setError(String(nextError)));
  }, [refreshSessions]);

  useEffect(() => {
    getModelConfig()
      .then(setModelConfig)
      .catch((nextError) => setError(String(nextError)));
  }, []);

  useEffect(() => {
    refreshActiveSession().catch((nextError) => setError(String(nextError)));
  }, [refreshActiveSession]);

  useEffect(() => {
    if (!activeSessionId || runtimeState?.session_id !== activeSessionId || !runtimeState.active) {
      setMemoryView(null);
      setSkillList(null);
      setSelectedSkill(null);
      setMcpTools(null);
      return;
    }
    if (!taskOpen) {
      return;
    }
    if (inspectorView === "memory") {
      refreshMemory().catch((nextError) => setError(String(nextError)));
    }
    if (inspectorView === "skills") {
      refreshSkills().catch((nextError) => setError(String(nextError)));
    }
    if (inspectorView === "mcp") {
      refreshMcpTools().catch((nextError) => setError(String(nextError)));
    }
  }, [
    activeSessionId,
    inspectorView,
    refreshMemory,
    refreshSkills,
    refreshMcpTools,
    runtimeState?.active,
    runtimeState?.session_id,
    taskOpen,
  ]);

  useEffect(() => {
    let disposed = false;
    let reconnectAttempt = 0;

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
    setConnectionStatus("connecting");

    const connect = (isReconnect = false) => {
      if (disposed) {
        return;
      }
      setConnectionStatus(isReconnect ? "reconnecting" : "connecting");
      const socket = openRunSocket(activeSessionId, (event) => {
        if (socketRef.current !== socket) {
          return;
        }
        if (event.type === "server_ready") {
          reconnectAttempt = 0;
          setConnectionStatus("ready");
          const nextRuntimeState = runtimeStateFromPayload(event.payload.runtime);
          if (nextRuntimeState) {
            applyRuntimeState(nextRuntimeState);
            if (nextRuntimeState.running && nextRuntimeState.status === "streaming_assistant") {
              restoreStreamingMessageFromTrace(
                nextRuntimeState.session_id,
                nextRuntimeState.active_turn_id,
              ).catch((nextError) => setError(String(nextError)));
            }
          }
          const pending = pendingFirstMessageRef.current;
          if (pending?.sessionId === activeSessionId) {
            pendingFirstMessageRef.current = null;
            void runSessionMessage(pending.sessionId, pending.content);
          }
          if (isReconnect) {
            refreshActiveSession().catch((nextError) => setError(String(nextError)));
            refreshSessions().catch((nextError) => setError(String(nextError)));
          }
          return;
        }
        if (event.type === "server_error") {
          const code = typeof event.payload.code === "string" ? event.payload.code : "";
          if (code === "session_running" && pendingSentMessageRef.current) {
            setDraft(pendingSentMessageRef.current);
          }
          setError(formatServerError(event.payload));
          pendingFirstMessageRef.current = null;
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
                  pending_approval: null,
                  notices: current?.session_id === activeSessionId ? current.notices : [],
                }));
              }
            })
            .catch((nextError) => {
              setError(String(nextError));
              runningSessionIdRef.current = "";
              pendingSentMessageRef.current = "";
              setBusy(false);
            });
          refreshSessions().catch((nextError) => setError(String(nextError)));
        }
      });
      socketRef.current = socket;
      socket.onclose = () => {
        if (socketRef.current === socket) {
          if (activeSessionId) {
            getRuntimeState(activeSessionId)
              .then((nextRuntimeState) =>
                applyRuntimeState({ ...nextRuntimeState, connected: false }),
              )
              .catch(() => {
                setRuntimeState((current) =>
                  current && current.session_id === activeSessionId
                    ? { ...current, connected: false }
                    : current,
                );
              });
          }
          if (!disposed) {
            const delay = RUN_SOCKET_RECONNECT_DELAYS_MS[reconnectAttempt];
            if (delay === undefined) {
              setConnectionStatus("connecting");
              setError("Run socket disconnected. Refresh or switch sessions to reconnect.");
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
        if (socketRef.current === socket) {
          pendingFirstMessageRef.current = null;
          if (activeSessionId) {
            getRuntimeState(activeSessionId)
              .then((nextRuntimeState) =>
                applyRuntimeState({ ...nextRuntimeState, connected: false }),
              )
              .catch(() => {
                runningSessionIdRef.current = "";
                pendingSentMessageRef.current = "";
                setBusy(false);
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
    appendStreamingDelta,
    applyRuntimeState,
    clearLiveTurnState,
    refreshActiveSession,
    refreshSessions,
    runSessionMessage,
  ]);

  const chatItems = useMemo(() => transcriptToChatItems(messages, inspection), [inspection, messages]);
  const visibleChatItems = useMemo(() => [...chatItems, ...liveToolItems], [chatItems, liveToolItems]);
  const activeSession = sessions.find((session) => session.session_id === activeSessionId);
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
  const runtimeNotices =
    runtimeState?.session_id === activeSessionId ? runtimeState.notices ?? [] : [];
  const composerDisabled =
    currentSessionRunning || Boolean(activeSessionId && connectionStatus !== "ready");
  const statusLabel = !activeSessionId
    ? "Draft"
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

  async function handleCreateSession() {
    setError("");
    setActiveSessionId("");
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
  }

  async function handleDeleteSession(sessionId: string) {
    if (!window.confirm("Delete this session?")) {
      return;
    }
    setError("");
    try {
      await deleteSession(sessionId);
      setSessions((current) => {
        const nextSessions = current.filter((session) => session.session_id !== sessionId);
        if (activeSessionId === sessionId) {
          setActiveSessionId(nextSessions[0]?.session_id ?? "");
        }
        return nextSessions;
      });
    } catch (nextError) {
      setError(String(nextError));
    }
  }

  async function submitMessage() {
    const content = draft.trim();
    if (!content || composerDisabled) {
      return;
    }
    setDraft("");
    pendingSentMessageRef.current = content;
    setBusy(true);
    setError("");
    clearLiveTurnState();
    setMessages((current) => [...current, { role: "user", content }]);
    try {
      if (!activeSessionId) {
        const session = await createSession();
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
        setActiveSessionId(session.session_id);
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
            <button className="primary-button" type="button" onClick={handleCreateSession}>
              <MessageSquarePlus size={17} />
              New session
            </button>
            <div className="session-list">
              {sessions.map((session) => (
                <div
                  className={`session-item ${session.session_id === activeSessionId ? "active" : ""}`}
                  key={session.session_id}
                >
                  <button
                    className="session-select"
                    type="button"
                    onClick={() => setActiveSessionId(session.session_id)}
                  >
                    <span>{session.title || "(untitled)"}</span>
                    <small>{shortSessionId(session.session_id)}</small>
                  </button>
                  <button
                    className="session-delete"
                    type="button"
                    onClick={() => void handleDeleteSession(session.session_id)}
                    title="Delete session"
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
              ))}
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
            <h2>{activeSession?.title || "New session"}</h2>
            <p>{activeSessionId || "Session will be created on first message"}</p>
          </div>
        </header>

        {error && (
          <div className="error-banner">
            <AlertCircle size={16} />
            {error}
          </div>
        )}

        {approvalRequest && (
          <div className="approval-banner">
            <div>
              <strong>Approval required</strong>
              <p>{approvalRequest.reason}</p>
              <code>{approvalRequest.subject}</code>
            </div>
            <div className="approval-actions">
              <button className="approval-deny" type="button" onClick={() => respondToApproval(false)}>
                Deny
              </button>
              <button className="approval-allow" type="button" onClick={() => respondToApproval(true)}>
                Approve
              </button>
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
              disabled={currentSessionRunning}
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
              <div className="model-config-pill" title="Model configuration">
                <span>{modelConfig?.model || "Model unavailable"}</span>
                {modelConfig?.base_url_host && <small>{modelConfig.base_url_host}</small>}
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
            {inspectorView === "task" && !currentSessionActive ? (
              <p className="muted">Chat with lulu in this session to load task state.</p>
            ) : inspectorView === "task" && taskState ? (
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
            ) : inspectorView === "task" ? (
              <p className="muted">No task state.</p>
            ) : inspectorView === "memory" ? (
              <div className="knowledge-block">
                <div className="knowledge-header">
                  <strong>Memory</strong>
                  <button className="text-button" type="button" onClick={() => void refreshMemory()}>
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
                  <button className="text-button" type="button" onClick={() => void refreshMcpTools()}>
                    Refresh
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
    </main>
  );
}
