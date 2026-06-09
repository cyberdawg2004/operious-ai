"use client";

import type { ReactNode } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Eye,
  RefreshCw,
  Search,
  XCircle,
} from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-state";
import { listSessions, type SessionRecord } from "@/lib/api";
import { useApiResource } from "@/lib/use-api-resource";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 100;
const REFRESH_INTERVAL_MS = 30_000;

type LifecycleFilter = "all" | "initiated" | "completed" | "suspended" | "failed";

type StatusDefinition = {
  label: string;
  icon: typeof Activity;
  color: string;
  bgColor: string;
  borderColor: string;
};

const lifecycleFilters: { id: LifecycleFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "initiated", label: "Processing" },
  { id: "completed", label: "Resolved" },
  { id: "suspended", label: "Suspended" },
  { id: "failed", label: "Failed" },
];

const lifecycleConfig: Record<Exclude<LifecycleFilter, "all">, StatusDefinition> = {
  initiated: {
    label: "Processing",
    icon: Clock,
    color: "text-blue-system",
    bgColor: "bg-blue-system/10",
    borderColor: "border-blue-system/20",
  },
  completed: {
    label: "Resolved",
    icon: CheckCircle2,
    color: "text-green-success",
    bgColor: "bg-green-success/10",
    borderColor: "border-green-success/20",
  },
  suspended: {
    label: "Suspended",
    icon: AlertTriangle,
    color: "text-warning-amber",
    bgColor: "bg-[#B8821C]/10",
    borderColor: "border-[#B8821C]/25",
  },
  failed: {
    label: "Failed",
    icon: XCircle,
    color: "text-red-alert",
    bgColor: "bg-red-alert/10",
    borderColor: "border-red-alert/20",
  },
};

const timelineReadyStatus: StatusDefinition = {
  label: "Timeline Ready",
  icon: CheckCircle2,
  color: "text-green-success",
  bgColor: "bg-green-success/10",
  borderColor: "border-green-success/20",
};

const openedStatus: StatusDefinition = {
  label: "Opened",
  icon: Clock,
  color: "text-ink-tertiary",
  bgColor: "bg-surface-sunken",
  borderColor: "border-border-subtle",
};

type OperationsData = {
  sessions: SessionRecord[];
  total: number;
  fetchedAt: string;
};

interface OperationsQueueProps {
  className?: string;
  onOpenTrace?: (sessionId: string) => void;
}

export function OperationsQueue({ className, onOpenTrace }: OperationsQueueProps) {
  const [activeFilter, setActiveFilter] = useState<LifecycleFilter>("all");
  const [searchQuery, setSearchQuery] = useState("");

  const loadOperations = useCallback(async (): Promise<OperationsData> => {
    const page = await listSessions({ limit: PAGE_SIZE, offset: 0 });
    return {
      sessions: [...page.items].sort(compareSessionsByOpenedAtDesc),
      total: page.total,
      fetchedAt: new Date().toISOString(),
    };
  }, []);

  const { data, error, isLoading, reload } = useApiResource(loadOperations);

  useEffect(() => {
    const intervalId = window.setInterval(() => {
      reload();
    }, REFRESH_INTERVAL_MS);

    return () => window.clearInterval(intervalId);
  }, [reload]);

  const filteredSessions = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    const sessions = data?.sessions ?? [];

    return sessions.filter((session) => {
      const matchesLifecycle =
        activeFilter === "all" || getQueueStatusId(session) === activeFilter;
      const matchesQuery =
        !query ||
        session.session_id.toLowerCase().includes(query) ||
        session.external_handle.toLowerCase().includes(query);

      return matchesLifecycle && matchesQuery;
    });
  }, [activeFilter, data?.sessions, searchQuery]);

  const recordedEventCount = useMemo(
    () =>
      (data?.sessions ?? []).reduce(
        (total, session) => total + Math.max(0, session.sequence_head + 1),
        0
      ),
    [data?.sessions]
  );

  return (
    <main className={cn("min-w-0 flex-1 overflow-auto bg-canvas px-4 py-5 sm:px-6 lg:px-8", className)}>
      <div className="mb-2 font-mono text-[11px] uppercase tracking-[0.18em] text-ink-tertiary">
        OPERATIONS - PILOT DEPLOYMENT — CONSUMER ELECTRONICS
      </div>

      <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <h1 className="font-display text-[32px] font-bold text-ink-primary">
          Operations Queue
        </h1>

        <div className="flex flex-col gap-3 md:flex-row md:items-center">
          <label className="flex flex-col gap-1">
            <span className="sr-only">Lifecycle phase</span>
            <select
              value={activeFilter}
              onChange={(event) => setActiveFilter(event.target.value as LifecycleFilter)}
              className="h-11 min-w-[180px] rounded border border-border-subtle bg-surface px-3 text-[13px] text-ink-primary outline-none transition-colors focus:border-border-defined sm:h-10"
            >
              {lifecycleFilters.map((filter) => (
                <option key={filter.id} value={filter.id}>
                  {filter.label}
                </option>
              ))}
            </select>
          </label>

          <div className="relative">
            <Search
              size={14}
              strokeWidth={1.5}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-tertiary"
            />
            <input
              type="text"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="Session ID or handle..."
              className="h-11 w-full min-w-0 rounded border border-border-subtle bg-surface pl-9 pr-3 text-[13px] text-ink-primary placeholder:text-ink-tertiary transition-colors focus:border-border-defined focus:outline-none sm:h-10 md:w-[320px]"
            />
          </div>

          <button
            type="button"
            onClick={reload}
            className="flex h-11 w-11 items-center justify-center rounded border border-border-subtle bg-surface transition-all duration-160 hover:border-border-defined sm:h-10 sm:w-10"
            aria-label="Refresh sessions"
          >
            <RefreshCw
              size={14}
              strokeWidth={1.5}
              className={cn("text-ink-secondary", isLoading && "animate-spin")}
            />
          </button>
        </div>
      </div>

      {isLoading && <div className="mt-8"><LoadingState label="Loading sessions..." /></div>}

      {error && !isLoading && (
        <div className="mt-8">
          <ErrorState
            title="Unable to load sessions"
            message={`Sessions request failed: ${error}`}
            actionLabel="Retry"
            onAction={reload}
          />
        </div>
      )}

      {data && !isLoading && !error && (
        <>
          <div className="mt-6 grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-4">
            <SummaryCard label="TENANT SESSIONS" value={String(data.total)} />
            <SummaryCard label="VISIBLE" value={String(filteredSessions.length)} />
            <SummaryCard
              label="TENANT EVENTS"
              value={String(recordedEventCount)}
              valueColor="text-gold-primary"
            />
          </div>

          <div className="mt-6 overflow-hidden rounded-lg border border-border-subtle bg-surface">
            {filteredSessions.length === 0 ? (
              <div className="p-6">
                <EmptyState
                  title="No sessions recorded yet."
                  message="Sessions appear here once tickets are processed through the pipeline."
                  actionLabel="Refresh"
                  onAction={reload}
                />
              </div>
            ) : (
              <div className="overflow-x-auto">
                <div className="min-w-[960px]">
                  <div className="flex h-11 items-center border-b border-border-subtle bg-surface-raised px-3 sm:h-9">
                    <TableHeader className="w-[132px]">SESSION ID</TableHeader>
                    <TableHeader className="min-w-[260px] flex-1">HANDLE</TableHeader>
                    <TableHeader className="w-[156px]">TIMELINE</TableHeader>
                    <TableHeader className="w-[156px]">OPENED</TableHeader>
                    <TableHeader className="w-[96px]">EVENTS</TableHeader>
                    <TableHeader className="w-[140px] text-right">ACTION</TableHeader>
                  </div>

                  {filteredSessions.map((session, index) => (
                    <SessionRow
                      key={session.session_id}
                      session={session}
                      isOdd={index % 2 === 1}
                      onOpenTrace={() => onOpenTrace?.(session.session_id)}
                    />
                  ))}
                </div>
              </div>
            )}

            <div className="flex min-h-12 flex-col gap-2 border-t border-border-subtle px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
              <span className="text-[12px] text-ink-tertiary">
                Showing {filteredSessions.length} of {data.total} sessions
              </span>
              <span className="font-technical text-[11px] uppercase tracking-[0.12em] text-ink-tertiary">
                Last refreshed {formatRelativeTime(data.fetchedAt)}
              </span>
            </div>
          </div>
        </>
      )}
    </main>
  );
}

function SummaryCard({
  label,
  value,
  valueColor = "text-ink-primary",
}: {
  label: string;
  value: string;
  valueColor?: string;
}) {
  return (
    <div className="flex h-20 flex-col gap-1.5 rounded-lg border border-border-subtle bg-surface p-4">
      <span className="font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-ink-tertiary">
        {label}
      </span>
      <span className={cn("font-technical text-[26px] font-medium tabular-nums", valueColor)}>
        {value}
      </span>
    </div>
  );
}

function TableHeader({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("px-2 font-technical text-[10px] font-semibold uppercase tracking-[0.16em] text-ink-tertiary", className)}>
      {children}
    </div>
  );
}

function SessionRow({
  session,
  isOdd,
  onOpenTrace,
}: {
  session: SessionRecord;
  isOdd: boolean;
  onOpenTrace: () => void;
}) {
  return (
    <div
      className={cn(
        "flex min-h-14 items-center border-b border-border-subtle px-3 last:border-b-0 sm:min-h-11",
        isOdd ? "bg-canvas/50" : "bg-surface",
        "transition-colors duration-160 hover:bg-[var(--surface-sunken)]"
      )}
    >
      <DataCell className="w-[132px]" value={shortSessionId(session.session_id)} accent />
      <div className="min-w-[260px] flex-1 px-2">
        <span className="block truncate font-technical text-[12px] text-ink-primary">
          {session.external_handle}
        </span>
        <span className="block truncate text-[11px] text-ink-tertiary">
          tenant {session.tenant_id ?? "unscoped"}
        </span>
      </div>
      <div className="w-[156px] px-2">
        <StatusBadge status={getQueueStatusDefinition(session)} />
      </div>
      <div className="w-[156px] px-2">
        <span
          className="block truncate font-technical text-[12px] tabular-nums text-ink-secondary"
          title={formatAbsoluteTime(session.opened_at)}
        >
          {formatAbsoluteTime(session.opened_at)}
        </span>
      </div>
      <DataCell className="w-[96px]" value={String(Math.max(0, session.sequence_head + 1))} />
      <div className="flex w-[140px] justify-end px-2">
        <TraceButton sessionId={session.session_id} onOpenTrace={onOpenTrace} />
      </div>
    </div>
  );
}

function TraceButton({
  sessionId,
  onOpenTrace,
}: {
  sessionId: string;
  onOpenTrace: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onOpenTrace}
      className="inline-flex h-11 items-center gap-2 rounded border border-border-subtle px-3 font-technical text-[10px] uppercase tracking-[0.12em] text-ink-secondary transition-all duration-160 hover:border-border-defined hover:bg-surface-raised hover:text-ink-primary sm:h-8"
      aria-label={`View trace for session ${sessionId}`}
    >
      <Eye size={13} strokeWidth={1.5} />
      View Trace
    </button>
  );
}

function StatusBadge({ status }: { status: StatusDefinition }) {
  const StatusIcon = status.icon;

  return (
    <div
      className={cn(
        "inline-flex items-center gap-1.5 rounded border px-2 py-1",
        status.bgColor,
        status.borderColor
      )}
    >
      <StatusIcon size={12} strokeWidth={1.5} className={status.color} />
      <span className={cn("font-technical text-[10px] font-medium tracking-wider", status.color)}>
        {status.label}
      </span>
    </div>
  );
}

function DataCell({
  className,
  value,
  accent = false,
}: {
  className: string;
  value: string;
  accent?: boolean;
}) {
  return (
    <div className={cn("px-2", className)}>
      <span
        className={cn(
          "block truncate font-technical text-[12px] tabular-nums",
          accent ? "text-blue-system" : "text-ink-secondary"
        )}
      >
        {value}
      </span>
    </div>
  );
}

function shortSessionId(value: string): string {
  return value.slice(0, 8);
}

function compareSessionsByOpenedAtDesc(left: SessionRecord, right: SessionRecord): number {
  return new Date(right.opened_at).getTime() - new Date(left.opened_at).getTime();
}

function getQueueStatusId(session: SessionRecord): Exclude<LifecycleFilter, "all"> {
  if (session.lifecycle_phase === "completed") return "completed";
  if (session.lifecycle_phase === "suspended") return "suspended";
  if (session.lifecycle_phase === "failed") return "failed";
  if (session.sequence_head >= 2) return "completed";
  return "initiated";
}

function getQueueStatusDefinition(session: SessionRecord): StatusDefinition {
  if (session.lifecycle_phase === "completed") return lifecycleConfig.completed;
  if (session.lifecycle_phase === "suspended") return lifecycleConfig.suspended;
  if (session.lifecycle_phase === "failed") return lifecycleConfig.failed;
  if (session.sequence_head >= 2) return timelineReadyStatus;
  if (session.sequence_head >= 0) return openedStatus;
  return unknownStatus(session.lifecycle_phase);
}

function unknownStatus(label: string): StatusDefinition {
  return {
    label: label || "unknown",
    icon: Activity,
    color: "text-ink-tertiary",
    bgColor: "bg-surface-sunken",
    borderColor: "border-border-subtle",
  };
}

function formatRelativeTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "unknown";

  const diffMs = Date.now() - date.getTime();
  const absMs = Math.abs(diffMs);
  const units = [
    { label: "d", ms: 86_400_000 },
    { label: "h", ms: 3_600_000 },
    { label: "m", ms: 60_000 },
  ];

  for (const unit of units) {
    if (absMs >= unit.ms) {
      const valueInUnit = Math.floor(absMs / unit.ms);
      return diffMs >= 0 ? `${valueInUnit}${unit.label} ago` : `in ${valueInUnit}${unit.label}`;
    }
  }

  return diffMs >= 0 ? "just now" : "in less than 1m";
}

function formatAbsoluteTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Invalid date";
  return date.toISOString();
}
