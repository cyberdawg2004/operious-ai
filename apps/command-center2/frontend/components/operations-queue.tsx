"use client";

import { useCallback, useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock,
  Eye,
  Pause,
  RefreshCw,
  Search,
  XCircle,
} from "lucide-react";
import {
  listSessions,
  readOperationalMetrics,
  type OperationalMetrics,
  type SessionRecord,
} from "@/lib/api";
import { useApiResource } from "@/lib/use-api-resource";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-state";

const PAGE_SIZE = 25;

const statusConfig = {
  running: {
    label: "RUNNING",
    icon: Clock,
    color: "text-blue-system",
    bgColor: "bg-blue-system/10",
    borderColor: "border-blue-system/20",
  },
  escalated: {
    label: "ESCALATED",
    icon: AlertTriangle,
    color: "text-warning-amber",
    bgColor: "bg-[#B8821C]/10",
    borderColor: "border-[#B8821C]/20",
  },
  completed: {
    label: "COMPLETED",
    icon: CheckCircle2,
    color: "text-green-success",
    bgColor: "bg-green-success/10",
    borderColor: "border-green-success/20",
  },
  failed: {
    label: "FAILED",
    icon: XCircle,
    color: "text-red-alert",
    bgColor: "bg-red-alert/10",
    borderColor: "border-red-alert/20",
  },
  paused: {
    label: "PAUSED",
    icon: Pause,
    color: "text-ink-tertiary",
    bgColor: "bg-ink-tertiary/10",
    borderColor: "border-ink-tertiary/20",
  },
} as const;

type Status = keyof typeof statusConfig;
type FilterPill = "All" | "Active" | "Escalated" | "Completed" | "Failed";

const filterPills: FilterPill[] = ["All", "Active", "Escalated", "Completed", "Failed"];

type OperationsData = {
  sessions: SessionRecord[];
  total: number;
  metrics: OperationalMetrics;
};

interface OperationsQueueProps {
  className?: string;
  onOpenTrace?: (traceId: string) => void;
}

export function OperationsQueue({ className, onOpenTrace }: OperationsQueueProps) {
  const [activeFilter, setActiveFilter] = useState<FilterPill>("All");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedRows, setSelectedRows] = useState<Set<string>>(new Set());
  const [currentPage, setCurrentPage] = useState(1);

  const loadOperations = useCallback(async (): Promise<OperationsData> => {
    const now = new Date();
    const windowStart = new Date(now.getTime() - 24 * 60 * 60 * 1000);
    const offset = (currentPage - 1) * PAGE_SIZE;
    const [sessionsPage, metrics] = await Promise.all([
      listSessions({ limit: PAGE_SIZE, offset }),
      readOperationalMetrics(windowStart, now),
    ]);
    return {
      sessions: sessionsPage.items,
      total: sessionsPage.total,
      metrics,
    };
  }, [currentPage]);

  const { data, error, isLoading, reload } = useApiResource(loadOperations);

  const filteredSessions = useMemo(() => {
    const sessions = data?.sessions ?? [];
    const normalizedQuery = searchQuery.trim().toLowerCase();
    return sessions.filter((session) => {
      const status = deriveStatus(session);
      const matchesFilter =
        activeFilter === "All" ||
        (activeFilter === "Active" && (status === "running" || status === "paused")) ||
        (activeFilter === "Escalated" && status === "escalated") ||
        (activeFilter === "Completed" && status === "completed") ||
        (activeFilter === "Failed" && status === "failed");
      if (!matchesFilter) return false;
      if (!normalizedQuery) return true;
      return [
        session.session_id,
        session.external_handle,
        session.principal_id,
        getClassification(session),
        getCustomerLabel(session),
      ]
        .filter((value): value is string => Boolean(value))
        .some((value) => value.toLowerCase().includes(normalizedQuery));
    });
  }, [activeFilter, data?.sessions, searchQuery]);

  const allFilteredSelected =
    filteredSessions.length > 0 &&
    filteredSessions.every((session) => selectedRows.has(session.session_id));

  const toggleRowSelection = (id: string) => {
    setSelectedRows((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const toggleAllRows = () => {
    if (allFilteredSelected) {
      setSelectedRows(new Set());
    } else {
      setSelectedRows(new Set(filteredSessions.map((session) => session.session_id)));
    }
  };

  return (
    <main className={cn("min-w-0 flex-1 overflow-auto bg-canvas px-4 py-5 sm:px-6 lg:px-8", className)}>
      <div className="eyebrow text-ink-tertiary mb-2">
        OPERATIONS · LIVE QUEUE
      </div>

      <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <h1 className="font-display font-bold text-[32px] text-ink-primary">
          Operations Queue
        </h1>

        <div className="flex flex-col gap-3 md:flex-row md:items-center">
          <div className="flex flex-wrap items-center gap-2">
            {filterPills.map((pill) => (
              <button
                key={pill}
                onClick={() => setActiveFilter(pill)}
                className={cn(
                  "min-h-11 px-3 py-1.5 rounded-full text-[12px] font-medium sm:min-h-0",
                  "border transition-all duration-160",
                  activeFilter === pill
                    ? "bg-ink-primary text-white border-ink-primary"
                    : "bg-transparent text-ink-secondary border-border-subtle hover:border-border-defined"
                )}
              >
                {pill}
              </button>
            ))}
          </div>

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
              placeholder="Session ID, principal, classification..."
              className={cn(
                "h-11 w-full min-w-0 rounded pl-9 pr-3 sm:h-10 md:w-[320px]",
                "bg-surface border border-border-subtle",
                "text-[13px] text-ink-primary placeholder:text-ink-tertiary",
                "focus:outline-none focus:border-border-defined",
                "transition-colors duration-160"
              )}
            />
          </div>

          <button
            onClick={reload}
            className={cn(
              "flex h-11 w-11 items-center justify-center rounded sm:h-10 sm:w-10",
              "border border-border-subtle bg-surface",
              "hover:border-border-defined transition-all duration-160"
            )}
            aria-label="Refresh operations data"
          >
            <RefreshCw
              size={14}
              strokeWidth={1.5}
              className={cn("text-ink-secondary", isLoading && "animate-spin")}
            />
          </button>
        </div>
      </div>

      {isLoading && <div className="mt-8"><LoadingState /></div>}

      {error && !isLoading && (
        <div className="mt-8">
          <ErrorState
            title="Operations data unavailable"
            message={error}
            onAction={reload}
          />
        </div>
      )}

      {data && !isLoading && !error && (
        <>
          <div className="mt-6 grid grid-cols-[repeat(auto-fit,minmax(240px,1fr))] gap-4">
            <SummaryCard label="TICKET THROUGHPUT" value={String(data.metrics.ticket_throughput)} />
            <SummaryCard
              label="ESCALATIONS"
              value={String(data.metrics.escalation_count)}
              valueColor="text-[#B8821C]"
            />
            <SummaryCard
              label="AVG EXECUTION LATENCY"
              value={formatLatency(data.metrics.execution_latency_ms_avg)}
            />
            <SummaryCard
              label="GOVERNANCE DENY RATE"
              value={`${(data.metrics.governance_deny_rate * 100).toFixed(1)}%`}
            />
          </div>

          <div className="mt-6 overflow-hidden rounded-lg border border-border-subtle bg-surface">
            {filteredSessions.length === 0 ? (
              <div className="p-6">
                <EmptyState
                  title="No sessions returned"
                  message="The backend returned no tenant-scoped sessions for the selected page and filters."
                  actionLabel="Refresh"
                  onAction={reload}
                />
              </div>
            ) : (
              <div className="overflow-x-auto">
                <div className="min-w-[1080px]">
                  <div className="flex h-11 items-center border-b border-border-subtle bg-surface-raised px-3 sm:h-9">
                    <div className="flex w-10 items-center justify-center">
                      <input
                        type="checkbox"
                        checked={allFilteredSelected}
                        onChange={toggleAllRows}
                        className="h-3.5 w-3.5 cursor-pointer rounded border-border-defined accent-gold"
                      />
                    </div>
                    <TableHeader className="w-[128px]">SESSION</TableHeader>
                    <TableHeader className="flex-1 min-w-[160px]">PRINCIPAL</TableHeader>
                    <TableHeader className="w-[180px]">CLASSIFICATION</TableHeader>
                    <TableHeader className="w-[120px]">STATUS</TableHeader>
                    <TableHeader className="w-[120px]">EVENTS</TableHeader>
                    <TableHeader className="w-[140px]">OPENED</TableHeader>
                    <TableHeader className="w-[96px]">AGE</TableHeader>
                    <TableHeader className="w-[80px] text-right">ACTIONS</TableHeader>
                  </div>

                  {filteredSessions.map((session, index) => (
                    <TableRow
                      key={session.session_id}
                      session={session}
                      isSelected={selectedRows.has(session.session_id)}
                      onSelect={() => toggleRowSelection(session.session_id)}
                      onOpenTrace={() => onOpenTrace?.(session.session_id)}
                      isOdd={index % 2 === 1}
                    />
                  ))}
                </div>
              </div>
            )}

            <div className="flex min-h-12 flex-col gap-3 border-t border-border-subtle px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
              <span className="text-[12px] text-ink-tertiary">
                Showing {filteredSessions.length} of {data.total} sessions
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setCurrentPage((page) => Math.max(1, page - 1))}
                  disabled={currentPage === 1}
                  className={cn(
                    "flex h-11 w-11 items-center justify-center rounded sm:h-8 sm:w-8",
                    "border border-border-subtle",
                    "disabled:opacity-50 disabled:cursor-not-allowed",
                    "hover:border-border-defined transition-colors"
                  )}
                  aria-label="Previous page"
                >
                  <ChevronLeft size={14} strokeWidth={1.5} className="text-ink-secondary" />
                </button>
                <span className="font-technical text-[12px] text-ink-secondary tabular-nums px-2">
                  Page {currentPage}
                </span>
                <button
                  onClick={() => setCurrentPage((page) => page + 1)}
                  disabled={currentPage * PAGE_SIZE >= data.total}
                  className={cn(
                    "flex h-11 w-11 items-center justify-center rounded sm:h-8 sm:w-8",
                    "border border-border-subtle",
                    "disabled:opacity-50 disabled:cursor-not-allowed",
                    "hover:border-border-defined transition-colors"
                  )}
                  aria-label="Next page"
                >
                  <ChevronRight size={14} strokeWidth={1.5} className="text-ink-secondary" />
                </button>
              </div>
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
      <span className="eyebrow text-ink-tertiary">{label}</span>
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
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("px-2 font-technical text-[10px] font-semibold uppercase tracking-[0.16em] text-ink-tertiary", className)}>
      {children}
    </div>
  );
}

function TableRow({
  session,
  isSelected,
  onSelect,
  onOpenTrace,
  isOdd,
}: {
  session: SessionRecord;
  isSelected: boolean;
  onSelect: () => void;
  onOpenTrace: () => void;
  isOdd: boolean;
}) {
  const statusKey = deriveStatus(session);
  const status = statusConfig[statusKey];
  const StatusIcon = status.icon;

  return (
    <div
      className={cn(
        "flex h-12 items-center px-3 sm:h-10",
        "border-b border-border-subtle last:border-b-0",
        "transition-colors duration-160",
        isOdd ? "bg-canvas/50" : "bg-surface",
        "hover:bg-[var(--surface-sunken)]"
      )}
    >
      <div className="flex w-10 items-center justify-center">
        <input
          type="checkbox"
          checked={isSelected}
          onChange={onSelect}
          className="h-3.5 w-3.5 cursor-pointer rounded border-border-defined accent-gold"
        />
      </div>

      <div className="w-[128px] px-2">
        <span className="font-technical text-[12px] font-medium text-blue-system tabular-nums">
          {shortId(session.external_handle || session.session_id)}
        </span>
      </div>

      <div className="flex-1 min-w-[160px] px-2">
        <span className="block truncate text-[13px] text-ink-primary">
          {getCustomerLabel(session)}
        </span>
      </div>

      <div className="w-[180px] px-2">
        <span className="block truncate text-[13px] text-ink-secondary">
          {getClassification(session)}
        </span>
      </div>

      <div className="w-[120px] px-2">
        <div
          className={cn(
            "inline-flex items-center gap-1.5 px-2 py-1 rounded",
            status.bgColor,
            "border",
            status.borderColor
          )}
        >
          <StatusIcon size={12} strokeWidth={1.5} className={status.color} />
          <span className={cn("font-technical text-[10px] font-medium tracking-wider", status.color)}>
            {status.label}
          </span>
        </div>
      </div>

      <div className="w-[120px] px-2">
        <span className="font-technical text-[12px] text-ink-secondary tabular-nums">
          {session.sequence_head}
        </span>
      </div>

      <div className="w-[140px] px-2">
        <span className="font-technical text-[12px] text-ink-secondary tabular-nums">
          {formatDateTime(session.opened_at)}
        </span>
      </div>

      <div className="w-[96px] px-2">
        <span className="font-technical text-[12px] text-ink-secondary tabular-nums">
          {formatAge(session.opened_at, session.lifecycle_recorded_at)}
        </span>
      </div>

      <div className="w-[80px] px-2 flex justify-end">
        <button
          onClick={onOpenTrace}
          className={cn(
            "flex h-11 w-11 items-center justify-center rounded sm:h-8 sm:w-8",
            "border border-border-subtle",
            "hover:border-border-defined hover:bg-surface-raised",
            "transition-all duration-160"
          )}
          aria-label={`Open trace for session ${session.session_id}`}
        >
          <Eye size={14} strokeWidth={1.5} className="text-ink-secondary" />
        </button>
      </div>
    </div>
  );
}

function deriveStatus(session: SessionRecord): Status {
  const lifecycle = session.lifecycle_phase.toLowerCase();
  const reason = session.lifecycle_reason?.toLowerCase() ?? "";
  if (reason.includes("escalat")) return "escalated";
  if (lifecycle.includes("fail") || lifecycle.includes("error")) return "failed";
  if (lifecycle.includes("pause") || lifecycle.includes("hold")) return "paused";
  if (lifecycle.includes("complete") || lifecycle.includes("closed") || lifecycle.includes("resolved")) {
    return "completed";
  }
  return "running";
}

function getCustomerLabel(session: SessionRecord): string {
  return (
    firstString(
      session.metadata.customer_name,
      session.metadata.customer,
      session.context_attributes.customer_name,
      session.context_attributes.customer,
      session.principal_id
    ) || "Unassigned principal"
  );
}

function getClassification(session: SessionRecord): string {
  return (
    firstString(
      session.metadata.classification,
      session.metadata.intent,
      session.context_attributes.classification,
      session.context_attributes.intent,
      session.context_labels[0]
    ) || "Unclassified"
  );
}

function firstString(...values: unknown[]): string | null {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) {
      return value;
    }
  }
  return null;
}

function shortId(value: string): string {
  if (value.length <= 14) return value;
  return `${value.slice(0, 8)}...${value.slice(-4)}`;
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Invalid date";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatAge(openedAt: string, recordedAt: string): string {
  const start = new Date(openedAt).getTime();
  const end = new Date(recordedAt).getTime();
  if (Number.isNaN(start) || Number.isNaN(end)) return "Unknown";
  return formatDuration(Math.max(0, end - start));
}

function formatLatency(value: number | null): string {
  if (value === null) return "No data";
  return formatDuration(value);
}

function formatDuration(milliseconds: number): string {
  if (milliseconds < 1000) return `${Math.round(milliseconds)}ms`;
  const totalSeconds = Math.round(milliseconds / 1000);
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}m ${seconds}s`;
}
