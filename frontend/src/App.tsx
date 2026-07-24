import {
  Activity,
  AlertCircle,
  Bot,
  ListTree,
  MessageSquarePlus,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  RefreshCcw,
  Send,
  Trash2,
} from "lucide-react";
import { FormEvent, KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

import {
  createSession,
  deleteSession,
  getTaskState,
  inspectSession,
  listSessions,
  loadMessages,
  openRunSocket,
} from "./api";
import type {
  ChatItem,
  SessionInspection,
  SessionSummary,
  TaskState,
  ToolCallView,
  TranscriptMessage,
} from "./types";

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

function runtimeToolItem(event: { type: string; turn_id: string; payload: Record<string, unknown> }): ChatItem | null {
  const payload = event.payload;
  const toolCallId = String(payload.tool_call_id ?? "");
  const toolName = String(payload.tool_name ?? "tool");
  if (event.type === "tool_call") {
    return {
      id: `live-${event.turn_id}-${toolCallId}-call`,
      kind: "tool_call",
      title: `Tool call · ${toolName}`,
      assistantContent: "",
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

function transcriptToChatItems(messages: TranscriptMessage[]): ChatItem[] {
  return messages
    .filter((message) => message.role !== "system")
    .map((message, index) => {
      const id = `${message.turn_id ?? "message"}-${message.tool_call_id ?? message.role ?? "item"}-${index}`;
      if (message.role === "tool") {
        return {
          id,
          kind: "tool_result",
          title: `Tool result${message.tool_call_id ? ` · ${message.tool_call_id}` : ""}`,
          toolResult: parseJsonValue(message.content),
        };
      }
      if (message.role === "assistant" && message.tool_calls?.length) {
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
        return {
          id,
          kind: "tool_call",
          title: `Tool call · ${message.tool_calls.length}`,
          assistantContent: typeof message.content === "string" ? message.content : "",
          toolCalls,
        };
      }
      return {
        id,
        kind: message.role === "assistant" ? "assistant" : "user",
        content: typeof message.content === "string" ? message.content : "",
      };
    });
}

export function App() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState("");
  const [inspection, setInspection] = useState<SessionInspection | null>(null);
  const [messages, setMessages] = useState<TranscriptMessage[]>([]);
  const [taskState, setTaskState] = useState<TaskState | null>(null);
  const [liveToolItems, setLiveToolItems] = useState<ChatItem[]>([]);
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const [taskOpen, setTaskOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [eventStreamReady, setEventStreamReady] = useState(false);
  const [streamingMessage, setStreamingMessage] = useState("");
  const [expandedMessages, setExpandedMessages] = useState<Set<string>>(new Set());
  const socketRef = useRef<WebSocket | null>(null);
  const chatEndRef = useRef<HTMLDivElement | null>(null);
  const pendingFirstMessageRef = useRef<{ sessionId: string; content: string } | null>(null);
  const runningSessionIdRef = useRef("");

  const refreshSessions = useCallback(async () => {
    const nextSessions = await listSessions();
    setSessions(nextSessions);
  }, []);

  const refreshSession = useCallback(async (sessionId: string) => {
    const [nextInspection, nextMessages, nextTaskState] = await Promise.all([
      inspectSession(sessionId),
      loadMessages(sessionId),
      getTaskState(sessionId),
    ]);
    setInspection(nextInspection);
    setMessages(nextMessages);
    setTaskState(nextTaskState);
  }, []);

  const refreshActiveSession = useCallback(async () => {
    if (!activeSessionId) {
      setInspection(null);
      setMessages([]);
      setTaskState(null);
      setLiveToolItems([]);
      return;
    }
    if (pendingFirstMessageRef.current?.sessionId === activeSessionId) {
      return;
    }
    await refreshSession(activeSessionId);
  }, [activeSessionId, refreshSession]);

  const clearLiveTurnState = useCallback(() => {
    setStreamingMessage("");
    setLiveToolItems([]);
  }, []);

  const appendStreamingDelta = useCallback((delta: string) => {
    setStreamingMessage((current) => `${current}${delta}`);
  }, []);

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
      socketRef.current.send(JSON.stringify({ type: "user_message", content }));
    },
    [clearLiveTurnState],
  );

  useEffect(() => {
    refreshSessions().catch((nextError) => setError(String(nextError)));
  }, [refreshSessions]);

  useEffect(() => {
    refreshActiveSession().catch((nextError) => setError(String(nextError)));
  }, [refreshActiveSession]);

  useEffect(() => {
    socketRef.current?.close();
    clearLiveTurnState();
    setEventStreamReady(false);
    if (!activeSessionId) {
      return;
    }
    const socket = openRunSocket(activeSessionId, (event) => {
      if (socketRef.current !== socket) {
        return;
      }
      if (event.type === "server_ready") {
        setEventStreamReady(true);
        const pending = pendingFirstMessageRef.current;
        if (pending?.sessionId === activeSessionId) {
          pendingFirstMessageRef.current = null;
          void runSessionMessage(pending.sessionId, pending.content);
        }
        return;
      }
      if (event.type === "server_error") {
        setError(String(event.payload.message ?? "Event stream error"));
        pendingFirstMessageRef.current = null;
        runningSessionIdRef.current = "";
        setBusy(false);
        return;
      }
      if (event.type === "assistant_delta") {
        appendStreamingDelta(String(event.payload.delta ?? ""));
        return;
      }
      if (event.type === "assistant_message") {
        if (!event.payload.streamed) {
          clearLiveTurnState();
          appendStreamingDelta(String(event.payload.content ?? ""));
        }
        return;
      }
      if (event.type === "tool_call" || event.type === "tool_result") {
        const item = runtimeToolItem(event);
        if (item) {
          setLiveToolItems((current) => [...current, item]);
        }
        return;
      }
      if (event.type === "turn_end") {
        refreshActiveSession()
          .then(() => {
            clearLiveTurnState();
            runningSessionIdRef.current = "";
            setBusy(false);
          })
          .catch((nextError) => {
            setError(String(nextError));
            runningSessionIdRef.current = "";
            setBusy(false);
          });
        refreshSessions().catch((nextError) => setError(String(nextError)));
      }
    });
    socketRef.current = socket;
    socket.onopen = () => {
      if (socketRef.current === socket) {
        setEventStreamReady(true);
      }
    };
    socket.onclose = () => {
      if (socketRef.current === socket) {
        setEventStreamReady(false);
        if (runningSessionIdRef.current === activeSessionId) {
          runningSessionIdRef.current = "";
          setBusy(false);
        }
      }
    };
    socket.onerror = () => {
      if (socketRef.current === socket) {
        setEventStreamReady(false);
        pendingFirstMessageRef.current = null;
        runningSessionIdRef.current = "";
        setBusy(false);
      }
    };
    return () => {
      if (socketRef.current === socket) {
        socketRef.current = null;
        setEventStreamReady(false);
      }
      socket.close();
    };
  }, [
    activeSessionId,
    appendStreamingDelta,
    clearLiveTurnState,
    refreshActiveSession,
    refreshSessions,
    runSessionMessage,
  ]);

  const chatItems = useMemo(() => transcriptToChatItems(messages), [messages]);
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
  const currentSessionRunning = Boolean(activeSessionId && busy && runningSessionIdRef.current === activeSessionId);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ block: "end" });
  }, [activeSessionId, visibleChatItems.length, showStreamingMessage]);

  async function handleCreateSession() {
    setError("");
    setActiveSessionId("");
    setInspection(null);
    setMessages([]);
    setTaskState(null);
    clearLiveTurnState();
    pendingFirstMessageRef.current = null;
    runningSessionIdRef.current = "";
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
    const currentRunning = Boolean(activeSessionId && runningSessionIdRef.current === activeSessionId);
    if (!content || currentRunning || (activeSessionId && !eventStreamReady)) {
      return;
    }
    setDraft("");
    setBusy(true);
    setError("");
    clearLiveTurnState();
    setMessages((current) => [...current, { role: "user", content }]);
    try {
      if (!activeSessionId) {
        const session = await createSession();
        runningSessionIdRef.current = session.session_id;
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
      setBusy(false);
    }
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
          <div className="status-pill">
            <Activity size={15} />
            {currentSessionRunning ? "Running" : activeSessionId ? eventStreamReady ? "Ready" : "Connecting" : "Draft"}
          </div>
        </header>

        {error && (
          <div className="error-banner">
            <AlertCircle size={16} />
            {error}
          </div>
        )}

        <div className="chat-list">
          {visibleChatItems.map((item) => (
            <article className={`chat-message ${item.kind}`} key={item.id}>
              <div className="message-role">{item.kind.replace("_", " ")}</div>
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
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={handleComposerKeyDown}
            placeholder="Ask lulu-agent..."
            rows={2}
          />
          <button
            className="send-button"
            disabled={!draft.trim() || currentSessionRunning || Boolean(activeSessionId && !eventStreamReady)}
            type="submit"
          >
            <Send size={18} />
          </button>
        </form>
      </section>

      <aside className={`inspector ${taskOpen ? "expanded" : "collapsed"}`}>
        {taskOpen ? (
          <section className="panel-section">
            <div className="section-title">
              <ListTree size={16} />
              Task
              <button
                className="icon-button"
                type="button"
                onClick={() => setTaskOpen(false)}
                title="Collapse task"
              >
                <PanelRightClose size={17} />
              </button>
            </div>
            {taskState ? (
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
          </section>
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
