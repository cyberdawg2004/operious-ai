"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Bot,
  Hand,
  MessageSquare,
  RefreshCw,
  Send,
  UserRound,
} from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-state";
import {
  listSessions,
  getInboxThread,
  sendOperatorConversationReply,
  type SessionRecord,
} from "@/lib/api";
import { getApiBaseUrl, getConfiguredTenantId } from "@/lib/api-client";
import { useApiResource } from "@/lib/use-api-resource";
import { cn } from "@/lib/utils";

const REFRESH_INTERVAL_MS = 10_000;

type ConversationEvent = {
  type: "turn" | "status" | "error";
  role?: "customer" | "assistant" | "operator" | "system";
  content?: string;
  turn_id?: string;
  phase?: "A" | "B" | "processing" | "complete" | string;
  governance_decision_id?: string;
  execution_id?: string;
  session_id?: string;
};

type ThreadMessage = {
  id: string;
  role: "customer" | "assistant" | "operator" | "system";
  content: string;
  phase?: string;
  executionId?: string;
  governanceDecisionId?: string;
};

export function ConversationsView() {
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const loadActiveSessions = useCallback(async () => {
    const page = await listSessions({ limit: 100, offset: 0, phase: "active" });
    return [...page.items].sort(compareSessionsByOpenedAtDesc);
  }, []);
  const { data, error, isLoading, reload } = useApiResource(loadActiveSessions);
  const sessions = useMemo(() => data ?? [], [data]);

  useEffect(() => {
    const intervalId = window.setInterval(reload, REFRESH_INTERVAL_MS);
    return () => window.clearInterval(intervalId);
  }, [reload]);

  const selectedSession = useMemo(
    () =>
      sessions.find((session) => session.session_id === selectedSessionId) ??
      sessions[0] ??
      null,
    [selectedSessionId, sessions]
  );

  if (isLoading && sessions.length === 0) {
    return <LoadingState label="Loading live customer chat" />;
  }
  if (error) {
    return (
      <ErrorState
        title="Live customer chat is unavailable"
        message={error}
        onAction={reload}
      />
    );
  }

  return (
    <main className="min-w-0 flex-1 overflow-auto bg-canvas px-4 py-5 sm:px-6 lg:px-8">
      <div className="flex min-h-[calc(100dvh-112px)] flex-col gap-4 lg:grid lg:grid-cols-[320px_minmax(0,1fr)]">
        <ConversationList
          sessions={sessions}
          selectedSessionId={selectedSession?.session_id ?? selectedSessionId}
          onSelect={setSelectedSessionId}
          onRefresh={reload}
        />
        {selectedSession ? (
          <ConversationThread
            key={selectedSession.session_id}
            session={selectedSession}
          />
        ) : (
          <div className="cc-panel-tight flex min-h-[420px] items-center justify-center">
            <EmptyState
              title="No live customer conversations"
              message="Active customer conversations will appear here when someone needs help right now."
            />
          </div>
        )}
      </div>
    </main>
  );
}

function ConversationList({
  sessions,
  selectedSessionId,
  onSelect,
  onRefresh,
}: {
  sessions: SessionRecord[];
  selectedSessionId: string | null;
  onSelect: (sessionId: string) => void;
  onRefresh: () => void;
}) {
  return (
    <section className="cc-panel-tight min-h-[260px] overflow-hidden">
      <div className="flex h-12 items-center justify-between border-b border-border-subtle px-3">
        <div className="flex items-center gap-2">
          <MessageSquare className="h-4 w-4 text-gold-primary" strokeWidth={1.8} />
          <span className="text-[13px] font-semibold text-ink-primary">Live Customer Chat</span>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          className="flex h-8 w-8 items-center justify-center rounded-md border border-border-subtle text-ink-secondary transition-colors hover:border-border-defined hover:text-ink-primary"
          aria-label="Refresh conversations"
          title="Refresh"
        >
          <RefreshCw className="h-3.5 w-3.5" strokeWidth={1.8} />
        </button>
      </div>
      <div className="max-h-[calc(100dvh-172px)] overflow-y-auto">
        {sessions.length === 0 ? (
          <div className="p-3">
            <EmptyState title="Queue is quiet" message="No sessions are currently active." />
          </div>
        ) : (
          <ul className="divide-y divide-border-subtle">
            {sessions.map((session) => {
              const active = session.session_id === selectedSessionId;
              return (
                <li key={session.session_id}>
                  <button
                    type="button"
                    onClick={() => onSelect(session.session_id)}
                    className={cn(
                      "flex w-full flex-col gap-2 px-3 py-3 text-left transition-colors",
                      active ? "bg-gold-bg" : "hover:bg-surface-raised"
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-[12px] font-semibold text-ink-primary">
                        {session.external_handle || "Customer conversation"}
                      </span>
                      <span className="rounded border border-border-subtle px-1.5 py-0.5 text-[10px] uppercase text-ink-tertiary">
                        {formatLifecycle(session.lifecycle_phase)}
                      </span>
                    </div>
                    <div className="truncate text-[11px] text-ink-secondary">
                      {session.context_notes?.trim() || "Open this chat to watch the live back-and-forth and step in if needed."}
                    </div>
                    <div className="flex items-center justify-between gap-3 text-[11.5px] text-ink-tertiary">
                      <span>{formatTime(session.opened_at)}</span>
                      <span>{Math.max(0, session.sequence_head + 1)} updates</span>
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}

function ConversationThread({ session }: { session: SessionRecord }) {
  const [messages, setMessages] = useState<ThreadMessage[]>([]);
  const [status, setStatus] = useState<string>("connecting");
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [sendError, setSendError] = useState<string | null>(null);
  const [operatorMode, setOperatorMode] = useState(false);
  const [draft, setDraft] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    setMessages([]);
    setHistoryError(null);
    void getInboxThread(session.session_id)
      .then((thread) => {
        if (cancelled) return;
        setMessages(
          thread.messages.map((message) => ({
            id: message.event_id,
            role: message.role,
            content: message.content,
            governanceDecisionId: message.governance_decision_id ?? undefined,
          }))
        );
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setHistoryError(error instanceof Error ? error.message : "Conversation history could not be loaded.");
      });
    return () => {
      cancelled = true;
    };
  }, [session.session_id]);

  useEffect(() => {
    const source = new EventSource(streamUrl(session.session_id), {
      withCredentials: true,
    });
    const handleEvent = (raw: MessageEvent<string>) => {
      const event = parseEvent(raw.data);
      if (!event) return;
      if (event.type === "status") {
        setStatus(String(event.phase ?? "idle"));
        return;
      }
      if (event.type === "turn" && event.content) {
        setMessages((current) => mergeMessage(current, event));
      }
    };
    source.addEventListener("turn", handleEvent);
    source.addEventListener("status", handleEvent);
    source.onmessage = handleEvent;
    source.onerror = () => setStatus((current) => (current === "complete" ? current : "waiting"));
    return () => source.close();
  }, [session.session_id]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, status]);

  const send = async () => {
    const content = draft.trim();
    if (!content || submitting) return;
    setSubmitting(true);
    setDraft("");
    setSendError(null);
    const optimisticId = `operator:${Date.now()}`;
    setMessages((current) => [
      ...current,
      { id: optimisticId, role: "operator", content },
    ]);
    try {
      const response = await sendOperatorConversationReply(session.session_id, content);
      setMessages((current) =>
        current.map((message) =>
          message.id === optimisticId ? { ...message, id: response.turn_id } : message
        )
      );
      setStatus("operator_reply_sent");
      setOperatorMode(true);
    } catch {
      setMessages((current) => current.filter((message) => message.id !== optimisticId));
      setSendError("Your reply could not be sent.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="cc-panel-tight flex min-h-[520px] min-w-0 flex-col overflow-hidden">
      <div className="flex h-12 items-center justify-between gap-3 border-b border-border-subtle px-4">
        <div className="min-w-0">
          <div className="text-[11px] uppercase text-ink-tertiary">
            {operatorMode ? "Operator takeover — your team is replying" : "Live customer conversation"}
          </div>
          <div className="truncate text-[13px] font-semibold text-ink-primary">
            {session.external_handle || "Customer conversation"}
          </div>
          <div className="text-[11px] text-ink-tertiary">
            {operatorMode
              ? "Messages you send go directly to the customer. AI replies shown here go to the customer, not to you."
              : "Step in here when you want your team to reply directly to the customer."}
          </div>
        </div>
        <span className="shrink-0 rounded border border-border-subtle px-2 py-1 text-[11px] uppercase text-ink-secondary">
          {formatLiveStatus(status)}
        </span>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        {historyError && (
          <div className="mb-3 rounded-md border border-amber-400/30 bg-amber-50 px-3 py-2 text-[12px] text-amber-700">
            {historyError}
          </div>
        )}
        {messages.length === 0 ? (
          <EmptyState
            title="Waiting for messages"
            message="Past messages will load here first, then new live updates will appear as they arrive."
          />
        ) : (
          <div className="space-y-3">
            {messages.map((message) => (
              <MessageBubble key={message.id} message={message} showAiDestinationLabel={operatorMode} />
            ))}
            {status === "processing" && !operatorMode && <TypingIndicator />}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      <div className="border-t border-border-subtle p-3">
        {!operatorMode ? (
          <button
            type="button"
            onClick={() => setOperatorMode(true)}
            className="flex h-9 items-center gap-2 rounded-md border border-border-subtle px-3 text-[12.5px] font-medium text-ink-secondary transition-colors hover:border-border-defined hover:text-ink-primary"
          >
            <Hand className="h-3.5 w-3.5" strokeWidth={1.8} />
            <span>Reply as your team</span>
          </button>
        ) : (
          <div className="space-y-2">
            <div className="text-[11px] text-ink-tertiary">
              Your message will be sent directly to the customer as a human reply. It will not ask the AI to answer for you.
            </div>
            {sendError && (
              <div className="rounded-md border border-red-alert/25 bg-red-alert/5 px-3 py-2 text-[12px] text-red-alert">
                {sendError}
              </div>
            )}
            <div className="flex gap-2">
              <input
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void send();
                }}
                className="min-w-0 flex-1 rounded-md border border-border-subtle bg-surface px-3 text-[13px] text-ink-primary outline-none transition-colors focus:border-border-defined"
                placeholder="Write the message you want the customer to receive..."
              />
              <button
                type="button"
                onClick={() => void send()}
                disabled={submitting || !draft.trim()}
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-border-subtle text-ink-secondary transition-colors hover:border-border-defined hover:text-ink-primary disabled:cursor-not-allowed disabled:opacity-50"
                aria-label="Send customer reply"
                title="Send"
              >
                <Send className="h-4 w-4" strokeWidth={1.8} />
              </button>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

function MessageBubble({ message, showAiDestinationLabel }: { message: ThreadMessage; showAiDestinationLabel?: boolean }) {
  const assistant = message.role === "assistant";
  const operator = message.role === "operator";
  return (
    <div className={cn("flex gap-2", assistant ? "justify-start" : "justify-end")}>
      {assistant && (
        <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-border-subtle bg-surface-raised text-gold-primary">
          <Bot className="h-3.5 w-3.5" strokeWidth={1.8} />
        </div>
      )}
      <div
        className={cn(
          "max-w-[min(680px,82%)] rounded-md border px-3 py-2 text-[13px] leading-5",
          assistant
            ? "border-border-subtle bg-surface text-ink-body"
            : operator
              ? "border-emerald-500/25 bg-emerald-500/10 text-ink-primary"
              : "border-blue-system/25 bg-blue-system/10 text-ink-primary"
        )}
      >
        {assistant && showAiDestinationLabel && (
          <div className="mb-1 text-[10px] font-medium uppercase tracking-[0.08em] text-gold-primary">
            AI reply → sent to customer
          </div>
        )}
        {operator && (
          <div className="mb-1 text-[10px] font-medium uppercase tracking-[0.08em] text-emerald-700">
            Sent by your team
          </div>
        )}
        <div className="whitespace-pre-wrap break-words">{message.content}</div>
        {message.phase && (
          <div className="mt-1 text-[10px] uppercase text-ink-tertiary">
            {formatPhase(message.phase)}
          </div>
        )}
      </div>
      {!assistant && (
        <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-border-subtle bg-surface-raised text-blue-system">
          <UserRound className="h-3.5 w-3.5" strokeWidth={1.8} />
        </div>
      )}
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="flex items-center gap-2 text-[12px] text-ink-tertiary">
      <span className="h-2 w-2 animate-pulse rounded-full bg-gold-primary" />
      <span>Preparing the AI reply</span>
    </div>
  );
}

function mergeMessage(current: ThreadMessage[], event: ConversationEvent): ThreadMessage[] {
  const id = event.turn_id ?? `${event.role}:${Date.now()}`;
  if (current.some((message) => message.id === id)) return current;
  return [
    ...current,
    {
      id,
      role: event.role ?? "system",
      content: event.content ?? "",
      phase: event.phase,
      executionId: event.execution_id,
      governanceDecisionId: event.governance_decision_id,
    },
  ];
}

function parseEvent(raw: string): ConversationEvent | null {
  try {
    const parsed = JSON.parse(raw) as ConversationEvent;
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

function streamUrl(sessionId: string): string {
  const url = new URL(`/conversation/${sessionId}/stream`, getApiBaseUrl());
  const tenantId = getConfiguredTenantId();
  if (tenantId) url.searchParams.set("tenant_id", tenantId);
  return url.toString();
}

function shortId(sessionId: string): string {
  return `${sessionId.slice(0, 8)}...${sessionId.slice(-4)}`;
}

function formatLifecycle(value: string): string {
  if (value === "active") return "Live";
  if (value === "terminated") return "Resolved";
  return value.replace(/_/g, " ");
}

function formatLiveStatus(value: string): string {
  if (value === "connecting") return "Connecting";
  if (value === "waiting") return "Waiting";
  if (value === "processing") return "AI replying";
  if (value === "operator_reply_sent") return "Reply sent";
  if (value === "complete") return "Up to date";
  return value.replace(/_/g, " ");
}

function formatPhase(value: string): string {
  if (value === "A") return "AI received the message";
  if (value === "B") return "AI reply ready";
  return value;
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    month: "short",
    day: "numeric",
  }).format(new Date(value));
}

function compareSessionsByOpenedAtDesc(a: SessionRecord, b: SessionRecord): number {
  return new Date(b.opened_at).getTime() - new Date(a.opened_at).getTime();
}
