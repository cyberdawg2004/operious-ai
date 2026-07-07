"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Bot,
  CheckCircle2,
  ChevronRight,
  Filter,
  GitMerge,
  Mail,
  MessageSquare,
  RefreshCw,
  Shield,
  ShieldAlert,
  ShieldCheck,
  UserRound,
  XCircle,
} from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-state";
import {
  getInboxThread,
  listInboxConversations,
  type InboxConversationSummary,
  type InboxGovernanceContext,
  type InboxThreadMessage,
  type InboxThreadResponse,
} from "@/lib/api";
import { useApiResource } from "@/lib/use-api-resource";
import { cn } from "@/lib/utils";

const CHANNEL_LABELS: Record<string, string> = {
  email: "Email",
  whatsapp: "WhatsApp",
  conversation_api: "Chat",
  unknown: "Unknown",
};

const PHASE_LABELS: Record<string, string> = {
  initiated: "Initiated",
  active: "Active",
  dormant: "Dormant",
  terminated: "Resolved",
  archived: "Archived",
};

const GOVERNANCE_VERDICT_LABELS: Record<string, string> = {
  allow: "Allowed",
  require_approval: "Held for Approval",
  escalate: "Escalated",
  deny: "Denied",
  degrade: "Degraded",
  redact: "Redacted",
};

type ChannelFilter = "all" | "email" | "whatsapp" | "conversation_api";
type PhaseFilter = "all" | "active" | "terminated" | "dormant";

export function ConversationInboxView() {
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [channelFilter, setChannelFilter] = useState<ChannelFilter>("all");
  const [phaseFilter, setPhaseFilter] = useState<PhaseFilter>("all");

  const loadConversations = useCallback(async () => {
    const page = await listInboxConversations({
      phase: phaseFilter === "all" ? undefined : phaseFilter,
      channel: channelFilter === "all" ? undefined : channelFilter,
      limit: 100,
      offset: 0,
    });
    return page.items;
  }, [channelFilter, phaseFilter]);

  const { data, error, isLoading, reload } = useApiResource(loadConversations);
  const conversations = useMemo(() => data ?? [], [data]);

  const selectedConversation = useMemo(
    () =>
      conversations.find((c) => c.session_id === selectedSessionId) ??
      conversations[0] ??
      null,
    [selectedSessionId, conversations]
  );

  if (isLoading && conversations.length === 0) {
    return <LoadingState label="Loading conversation inbox" />;
  }
  if (error) {
    return (
      <ErrorState
        title="Inbox unavailable"
        message={error}
        onAction={reload}
      />
    );
  }

  return (
    <main className="min-w-0 flex-1 overflow-auto bg-canvas px-4 py-5 sm:px-6 lg:px-8">
      <div className="mb-4 flex items-center justify-between gap-4">
        <div>
          <h1 className="text-[15px] font-semibold text-ink-primary">
            Conversation Inbox
          </h1>
          <p className="text-[12px] text-ink-tertiary">
            Agent–customer conversations — read-only audit view
          </p>
        </div>
        <div className="flex items-center gap-2">
          <FilterBar
            channelFilter={channelFilter}
            phaseFilter={phaseFilter}
            onChannelChange={setChannelFilter}
            onPhaseChange={setPhaseFilter}
          />
          <button
            type="button"
            onClick={reload}
            className="flex h-8 w-8 items-center justify-center rounded-md border border-border-subtle text-ink-secondary transition-colors hover:border-border-defined hover:text-ink-primary"
            aria-label="Refresh inbox"
            title="Refresh"
          >
            <RefreshCw className="h-3.5 w-3.5" strokeWidth={1.8} />
          </button>
        </div>
      </div>

      <div className="flex min-h-[calc(100dvh-172px)] flex-col gap-4 lg:grid lg:grid-cols-[340px_minmax(0,1fr)]">
        <InboxList
          conversations={conversations}
          selectedSessionId={selectedConversation?.session_id ?? null}
          onSelect={setSelectedSessionId}
        />
        {selectedConversation ? (
          <ThreadPanel
            key={selectedConversation.session_id}
            conversation={selectedConversation}
          />
        ) : (
          <div className="cc-panel-tight flex min-h-[420px] items-center justify-center">
            <EmptyState
              title="No conversations"
              message="Select a conversation to view the thread."
            />
          </div>
        )}
      </div>
    </main>
  );
}

// ── Filter bar ────────────────────────────────────────────────────────────────

function FilterBar({
  channelFilter,
  phaseFilter,
  onChannelChange,
  onPhaseChange,
}: {
  channelFilter: ChannelFilter;
  phaseFilter: PhaseFilter;
  onChannelChange: (v: ChannelFilter) => void;
  onPhaseChange: (v: PhaseFilter) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <Filter className="h-3.5 w-3.5 text-ink-tertiary" strokeWidth={1.8} />
      <select
        value={channelFilter}
        onChange={(e) => onChannelChange(e.target.value as ChannelFilter)}
        className="h-8 rounded-md border border-border-subtle bg-surface px-2 text-[12px] text-ink-secondary transition-colors hover:border-border-defined focus:outline-none"
        aria-label="Filter by channel"
      >
        <option value="all">All channels</option>
        <option value="email">Email</option>
        <option value="whatsapp">WhatsApp</option>
        <option value="conversation_api">Chat</option>
      </select>
      <select
        value={phaseFilter}
        onChange={(e) => onPhaseChange(e.target.value as PhaseFilter)}
        className="h-8 rounded-md border border-border-subtle bg-surface px-2 text-[12px] text-ink-secondary transition-colors hover:border-border-defined focus:outline-none"
        aria-label="Filter by status"
      >
        <option value="all">All statuses</option>
        <option value="active">Active</option>
        <option value="terminated">Resolved</option>
        <option value="dormant">Dormant</option>
      </select>
    </div>
  );
}

// ── Conversation list (left panel) ────────────────────────────────────────────

function InboxList({
  conversations,
  selectedSessionId,
  onSelect,
}: {
  conversations: InboxConversationSummary[];
  selectedSessionId: string | null;
  onSelect: (sessionId: string) => void;
}) {
  return (
    <section className="cc-panel-tight min-h-[260px] overflow-hidden">
      <div className="flex h-11 items-center gap-2 border-b border-border-subtle px-3">
        <MessageSquare className="h-4 w-4 text-gold-primary" strokeWidth={1.8} />
        <span className="text-[13px] font-semibold text-ink-primary">
          Conversations
        </span>
        <span className="ml-auto rounded-full bg-surface-raised px-2 py-0.5 text-[10px] font-medium text-ink-tertiary">
          {conversations.length}
        </span>
      </div>
      <div className="max-h-[calc(100dvh-212px)] overflow-y-auto">
        {conversations.length === 0 ? (
          <div className="p-4">
            <EmptyState
              title="No conversations"
              message="No conversations match the current filters."
            />
          </div>
        ) : (
          <ul className="divide-y divide-border-subtle">
            {conversations.map((conv) => (
              <InboxListItem
                key={conv.session_id}
                conversation={conv}
                isSelected={conv.session_id === selectedSessionId}
                onSelect={onSelect}
              />
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function InboxListItem({
  conversation,
  isSelected,
  onSelect,
}: {
  conversation: InboxConversationSummary;
  isSelected: boolean;
  onSelect: (sessionId: string) => void;
}) {
  const channelLabel = CHANNEL_LABELS[conversation.channel] ?? conversation.channel;
  const phaseLabel = PHASE_LABELS[conversation.lifecycle_phase] ?? conversation.lifecycle_phase;

  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect(conversation.session_id)}
        className={cn(
          "flex w-full flex-col gap-1.5 px-3 py-3 text-left transition-colors",
          isSelected ? "bg-gold-bg" : "hover:bg-surface-raised"
        )}
      >
        <div className="flex items-center justify-between gap-2">
          <span className="truncate font-mono text-[12px] font-semibold text-ink-primary">
            {conversation.external_handle}
          </span>
          <ChannelBadge channel={conversation.channel} label={channelLabel} />
        </div>
        <div className="flex items-center gap-2 text-[11px] text-ink-tertiary">
          <PhaseDot phase={conversation.lifecycle_phase} />
          <span>{phaseLabel}</span>
          <span className="mx-1 text-border-defined">·</span>
          <span>{conversation.message_count} msg</span>
          {conversation.has_governance_context && (
            <>
              <span className="mx-1 text-border-defined">·</span>
              <Shield className="h-3 w-3 text-amber-500" strokeWidth={1.8} />
            </>
          )}
          {conversation.customer_identity_id && (
            <>
              <span className="mx-1 text-border-defined">·</span>
              <GitMerge className="h-3 w-3 text-blue-system" strokeWidth={1.8} />
            </>
          )}
        </div>
        {conversation.last_message_at && (
          <div className="text-[10.5px] text-ink-quaternary">
            {formatRelative(conversation.last_message_at)}
          </div>
        )}
      </button>
    </li>
  );
}

// ── Thread panel (right panel) ────────────────────────────────────────────────

function ThreadPanel({ conversation }: { conversation: InboxConversationSummary }) {
  const [includeSiblings, setIncludeSiblings] = useState(false);

  const loadThread = useCallback(async () => {
    return getInboxThread(conversation.session_id, includeSiblings);
  }, [conversation.session_id, includeSiblings]);

  const { data: thread, error, isLoading, reload } = useApiResource(loadThread);

  if (isLoading) {
    return (
      <section className="cc-panel-tight flex min-h-[520px] items-center justify-center">
        <LoadingState label="Loading thread" />
      </section>
    );
  }
  if (error) {
    return (
      <section className="cc-panel-tight flex min-h-[520px] items-center justify-center">
        <ErrorState title="Thread unavailable" message={error} onAction={reload} />
      </section>
    );
  }

  return (
    <section className="cc-panel-tight flex min-h-[520px] flex-col overflow-hidden">
      <ThreadHeader
        conversation={conversation}
        thread={thread ?? null}
        includeSiblings={includeSiblings}
        onToggleSiblings={() => setIncludeSiblings((v) => !v)}
      />
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        {!thread || thread.messages.length === 0 ? (
          <EmptyState
            title="No messages yet"
            message="No inbound or outbound messages have been recorded for this session."
          />
        ) : (
          <div className="space-y-3">
            {thread.messages.map((msg) => (
              <MessageBubble key={msg.event_id} message={msg} />
            ))}
          </div>
        )}
      </div>
      <div className="border-t border-border-subtle px-4 py-2">
        <p className="text-[11px] text-ink-quaternary">
          Read-only view — replies are sent via the agent pipeline.
        </p>
      </div>
    </section>
  );
}

function ThreadHeader({
  conversation,
  thread,
  includeSiblings,
  onToggleSiblings,
}: {
  conversation: InboxConversationSummary;
  thread: InboxThreadResponse | null;
  includeSiblings: boolean;
  onToggleSiblings: () => void;
}) {
  const channelLabel = CHANNEL_LABELS[conversation.channel] ?? conversation.channel;
  const phaseLabel = PHASE_LABELS[conversation.lifecycle_phase] ?? conversation.lifecycle_phase;

  return (
    <div className="flex flex-col gap-1 border-b border-border-subtle px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <ChannelBadge channel={conversation.channel} label={channelLabel} />
            <PhaseDot phase={conversation.lifecycle_phase} />
            <span className="text-[11px] text-ink-tertiary">{phaseLabel}</span>
          </div>
          <div className="mt-0.5 truncate font-mono text-[13px] font-semibold text-ink-primary">
            {conversation.external_handle}
          </div>
          <div className="font-mono text-[10px] text-ink-quaternary">
            {conversation.session_id}
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <div className="text-[11px] text-ink-tertiary">
            Opened {formatDate(conversation.opened_at)}
          </div>
          <div className="text-[11px] text-ink-tertiary">
            {thread?.total ?? 0} messages
          </div>
        </div>
      </div>
      {conversation.customer_identity_id && (
        <button
          type="button"
          onClick={onToggleSiblings}
          className={cn(
            "mt-1 flex items-center gap-1.5 self-start rounded-md border px-2 py-1 text-[11px] transition-colors",
            includeSiblings
              ? "border-blue-system/40 bg-blue-system/10 text-blue-system"
              : "border-border-subtle text-ink-tertiary hover:border-border-defined hover:text-ink-secondary"
          )}
        >
          <GitMerge className="h-3 w-3" strokeWidth={1.8} />
          <span>
            {includeSiblings ? "Showing cross-channel thread" : "Show cross-channel thread"}
          </span>
          <ChevronRight
            className={cn(
              "h-3 w-3 transition-transform",
              includeSiblings && "rotate-90"
            )}
            strokeWidth={1.8}
          />
        </button>
      )}
    </div>
  );
}

// ── Message bubble ────────────────────────────────────────────────────────────

function MessageBubble({ message }: { message: InboxThreadMessage }) {
  const isAssistant = message.role === "assistant";
  const [governanceOpen, setGovernanceOpen] = useState(false);

  return (
    <div className={cn("flex flex-col gap-1", isAssistant ? "items-start" : "items-end")}>
      <div className={cn("flex items-end gap-2", isAssistant ? "flex-row" : "flex-row-reverse")}>
        <div
          className={cn(
            "flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-border-subtle",
            isAssistant
              ? "bg-surface-raised text-gold-primary"
              : "bg-surface-raised text-blue-system"
          )}
        >
          {isAssistant ? (
            <Bot className="h-3.5 w-3.5" strokeWidth={1.8} />
          ) : (
            <UserRound className="h-3.5 w-3.5" strokeWidth={1.8} />
          )}
        </div>
        <div
          className={cn(
            "max-w-[min(640px,78%)] rounded-md border px-3 py-2 text-[13px] leading-5",
            isAssistant
              ? "border-border-subtle bg-surface text-ink-body"
              : "border-blue-system/25 bg-blue-system/10 text-ink-primary"
          )}
        >
          <div className="whitespace-pre-wrap break-words">{message.content}</div>
          <div className="mt-1 flex items-center gap-2">
            <span className="font-mono text-[10px] text-ink-quaternary">
              {formatTime(message.occurred_at)}
            </span>
            {isAssistant && message.governance && (
              <button
                type="button"
                onClick={() => setGovernanceOpen((v) => !v)}
                className="flex items-center gap-1 rounded px-1 py-0.5 text-[10px] transition-colors hover:bg-surface-raised"
                aria-label="Toggle governance context"
              >
                <GovernanceIcon verdict={message.governance.governance_verdict} />
                <span className="text-ink-tertiary">
                  {GOVERNANCE_VERDICT_LABELS[message.governance.governance_verdict] ??
                    message.governance.governance_verdict}
                </span>
              </button>
            )}
            {isAssistant && !message.governance && message.governance_decision_id && (
              <span className="flex items-center gap-1 text-[10px] text-ink-quaternary">
                <Shield className="h-2.5 w-2.5" strokeWidth={1.8} />
                Governed
              </span>
            )}
          </div>
        </div>
      </div>
      {isAssistant && message.governance && governanceOpen && (
        <GovernancePanel governance={message.governance} />
      )}
    </div>
  );
}

// ── Governance context panel ──────────────────────────────────────────────────

function GovernancePanel({ governance }: { governance: InboxGovernanceContext }) {
  const verdict = governance.governance_verdict;
  const autonomy = governance.autonomy_decision;
  const isDenied = verdict === "deny" || verdict === "escalate";

  return (
    <div
      className={cn(
        "ml-9 max-w-[min(600px,78%)] rounded-md border px-3 py-2.5",
        isDenied
          ? "border-red-alert/30 bg-red-alert/5"
          : "border-amber-500/30 bg-amber-500/5"
      )}
    >
      <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold text-ink-secondary">
        <Shield className="h-3.5 w-3.5 text-amber-500" strokeWidth={1.8} />
        Governance Context
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px]">
        <GovernanceRow label="Verdict" value={GOVERNANCE_VERDICT_LABELS[verdict] ?? verdict} />
        <GovernanceRow label="Autonomy" value={formatAutonomy(autonomy)} />
        <GovernanceRow label="Supervisor" value={formatSupervisor(governance.supervisor_verdict)} />
        <GovernanceRow label="Status" value={governance.status.replace(/_/g, " ")} />
        <GovernanceRow label="Category" value={governance.resolution_category} />
        <GovernanceRow
          label="Confidence"
          value={`${Math.round(governance.confidence * 100)}%`}
        />
      </dl>
      {governance.governance_decision_id && (
        <div className="mt-1.5 font-mono text-[10px] text-ink-quaternary">
          Decision: {governance.governance_decision_id.slice(0, 16)}…
        </div>
      )}
    </div>
  );
}

function GovernanceRow({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-ink-tertiary">{label}</dt>
      <dd className="font-medium text-ink-secondary capitalize">{value}</dd>
    </>
  );
}

// ── Small UI atoms ────────────────────────────────────────────────────────────

function ChannelBadge({ channel, label }: { channel: string; label: string }) {
  const icon =
    channel === "email" ? (
      <Mail className="h-2.5 w-2.5" strokeWidth={1.8} />
    ) : (
      <MessageSquare className="h-2.5 w-2.5" strokeWidth={1.8} />
    );
  return (
    <span className="flex items-center gap-1 rounded border border-border-subtle px-1.5 py-0.5 font-mono text-[10px] uppercase text-ink-tertiary">
      {icon}
      {label}
    </span>
  );
}

function PhaseDot({ phase }: { phase: string }) {
  const color =
    phase === "active"
      ? "bg-green-500"
      : phase === "terminated"
        ? "bg-ink-quaternary"
        : phase === "dormant"
          ? "bg-amber-500"
          : "bg-blue-system";
  return <span className={cn("inline-block h-1.5 w-1.5 rounded-full", color)} />;
}

function GovernanceIcon({ verdict }: { verdict: string }) {
  if (verdict === "allow") {
    return <CheckCircle2 className="h-3 w-3 text-green-600" strokeWidth={1.8} />;
  }
  if (verdict === "deny" || verdict === "escalate") {
    return <XCircle className="h-3 w-3 text-red-alert" strokeWidth={1.8} />;
  }
  if (verdict === "require_approval") {
    return <ShieldAlert className="h-3 w-3 text-amber-500" strokeWidth={1.8} />;
  }
  return <ShieldCheck className="h-3 w-3 text-amber-500" strokeWidth={1.8} />;
}

// ── Formatting helpers ────────────────────────────────────────────────────────

function formatTime(iso: string): string {
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    month: "short",
    day: "numeric",
  }).format(new Date(iso));
}

function formatDate(iso: string): string {
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(new Date(iso));
}

function formatRelative(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay}d ago`;
}

function formatAutonomy(decision: string): string {
  return (
    {
      auto_approved: "Auto-approved",
      needs_customer_info: "Needs customer info",
      needs_human_approval: "Needs human approval",
      denied: "Denied",
    }[decision] ?? decision.replace(/_/g, " ")
  );
}

function formatSupervisor(verdict: string): string {
  return (
    {
      pass: "Pass",
      needs_human_review: "Needs review",
      fail: "Fail",
    }[verdict] ?? verdict.replace(/_/g, " ")
  );
}
