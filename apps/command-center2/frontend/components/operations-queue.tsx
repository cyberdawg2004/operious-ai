"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Eye,
  RefreshCw,
  Search,
  XCircle,
} from "lucide-react";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { BarChart, DonutChart } from "@/components/ui/chart";
import { CodeAsReadableText, DownloadableLog } from "@/components/ui/readable-data";
import { StatusBadge, type StatusTone } from "@/components/ui/status-badge";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-state";
import { listSessions, type SessionRecord } from "@/lib/api";
import { useApiResource } from "@/lib/use-api-resource";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 100;
const REFRESH_INTERVAL_MS = 30_000;

type LifecycleFilter = "all" | "initiated" | "completed" | "suspended" | "failed";
type QueueStatusId = Exclude<LifecycleFilter, "all">;

type StatusMeta = {
  label: string;
  tone: StatusTone;
  icon: typeof Activity;
};

const lifecycleFilters: { id: LifecycleFilter; label: string }[] = [
  { id: "all", label: "All tickets" },
  { id: "initiated", label: "Processing" },
  { id: "completed", label: "Resolved" },
  { id: "suspended", label: "Suspended" },
  { id: "failed", label: "Failed" },
];

const statusMetaByQueueId: Record<QueueStatusId, StatusMeta> = {
  initiated: { label: "Processing", tone: "info", icon: Clock },
  completed: { label: "Resolved", tone: "success", icon: CheckCircle2 },
  suspended: { label: "Suspended", tone: "warning", icon: AlertTriangle },
  failed: { label: "Failed", tone: "danger", icon: XCircle },
};

const timelineReadyMeta: StatusMeta = { label: "Timeline ready", tone: "success", icon: CheckCircle2 };
const openedMeta: StatusMeta = { label: "Opened", tone: "neutral", icon: Clock };

const statusBreakdownColors: Record<QueueStatusId, string> = {
  initiated: "var(--chart-blue)",
  completed: "var(--chart-green)",
  suspended: "var(--chart-amber)",
  failed: "var(--chart-pink)",
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
  const [expandedSessionId, setExpandedSessionId] = useState<string | null>(null);

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
        session.external_handle.toLowerCase().includes(query) ||
        (session.context_notes ?? "").toLowerCase().includes(query);

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

  const statusBreakdown = useMemo(() => {
    const sessions = data?.sessions ?? [];
    const counts: Record<QueueStatusId, number> = {
      initiated: 0,
      completed: 0,
      suspended: 0,
      failed: 0,
    };
    for (const session of sessions) {
      counts[getQueueStatusId(session)] += 1;
    }
    return (Object.keys(counts) as QueueStatusId[]).map((id) => ({
      label: statusMetaByQueueId[id].label,
      value: counts[id],
      color: statusBreakdownColors[id],
    }));
  }, [data?.sessions]);

  const ticketVolume = useMemo(() => buildTicketVolume(data?.sessions ?? []), [data?.sessions]);
  const todayCount = ticketVolume[ticketVolume.length - 1]?.value ?? 0;
  const yesterdayCount = ticketVolume[ticketVolume.length - 2]?.value ?? 0;
  const todayDelta = todayCount - yesterdayCount;

  const columns: DataTableColumn<SessionRecord>[] = [
    {
      key: "customer",
      header: "Customer",
      width: "min-w-[260px]",
      render: (session) => (
        <div className="min-w-0">
          <p className="truncate text-[13.5px] font-semibold text-ink-primary">
            {session.external_handle}
          </p>
          <p className="mt-0.5 truncate text-meta">
            {session.context_notes?.trim() || "No ticket summary provided yet."}
          </p>
        </div>
      ),
    },
    {
      key: "status",
      header: "Status",
      width: "w-[170px]",
      render: (session) => {
        const meta = getQueueStatusMeta(session);
        return <StatusBadge label={meta.label} tone={meta.tone} icon={meta.icon} />;
      },
    },
    {
      key: "opened",
      header: "Opened",
      width: "w-[170px]",
      render: (session) => (
        <span className="tabular text-[12.5px] text-ink-secondary" title={formatAbsoluteTime(session.opened_at)}>
          {formatRelativeTime(session.opened_at)}
        </span>
      ),
    },
    {
      key: "events",
      header: "Events",
      width: "w-[90px]",
      numeric: true,
      render: (session) => (
        <span className="tabular text-[12.5px] text-ink-secondary">
          {Math.max(0, session.sequence_head + 1)}
        </span>
      ),
    },
    {
      key: "actions",
      header: "",
      width: "w-[230px]",
      align: "right",
      render: (session) => (
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={() => onOpenTrace?.(session.session_id)}
            className="cc-btn cc-btn-secondary"
            aria-label={`Review history for session ${session.session_id}`}
          >
            <Eye size={13} strokeWidth={1.8} />
            Review history
          </button>
          <button
            type="button"
            onClick={() =>
              setExpandedSessionId((current) =>
                current === session.session_id ? null : session.session_id
              )
            }
            className="cc-btn cc-btn-ghost"
            aria-label={`Toggle more details for session ${session.session_id}`}
            aria-expanded={expandedSessionId === session.session_id}
          >
            {expandedSessionId === session.session_id ? (
              <ChevronDown size={14} strokeWidth={1.8} />
            ) : (
              <ChevronRight size={14} strokeWidth={1.8} />
            )}
            More
          </button>
        </div>
      ),
    },
  ];

  return (
    <main className={cn("min-w-0 flex-1 overflow-auto bg-canvas px-4 py-5 sm:px-6 lg:px-8", className)}>
      <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <p className="text-meta">Current workspace</p>

        <div className="flex flex-col gap-3 md:flex-row md:items-center">
          <label className="flex flex-col gap-1">
            <span className="sr-only">Ticket status</span>
            <select
              value={activeFilter}
              onChange={(event) => setActiveFilter(event.target.value as LifecycleFilter)}
              className="cc-select h-10 min-w-[180px]"
            >
              {lifecycleFilters.map((filter) => (
                <option key={filter.id} value={filter.id}>
                  {filter.label}
                </option>
              ))}
            </select>
          </label>

          <div className="relative w-full md:w-[320px]">
            <Search
              size={14}
              strokeWidth={1.8}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-tertiary"
            />
            <input
              type="text"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="Search by customer or ticket ID..."
              className="cc-input h-10 pl-9"
            />
          </div>

          <button
            type="button"
            onClick={reload}
            className="cc-btn cc-btn-secondary h-10 w-10"
            aria-label="Refresh tickets"
          >
            <RefreshCw
              size={14}
              strokeWidth={1.8}
              className={cn(isLoading && "animate-spin")}
            />
          </button>
        </div>
      </div>

      {isLoading && <div className="mt-8"><LoadingState label="Loading tickets..." /></div>}

      {error && !isLoading && (
        <div className="mt-8">
          <ErrorState
            title="Unable to load tickets"
            message={`Sessions request failed: ${error}`}
            actionLabel="Retry"
            onAction={reload}
          />
        </div>
      )}

      {data && !isLoading && !error && (
        <>
          <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_minmax(0,1.4fr)]">
            <Card>
              <CardHeader>
                <div>
                  <CardTitle>Tickets</CardTitle>
                  <CardDescription>Across all open sessions</CardDescription>
                </div>
              </CardHeader>
              <p className="heading-page tabular">{data.total}</p>
              <div className="mt-4 flex items-center gap-2">
                <span
                  className={cn(
                    "cc-stat-pill",
                    todayDelta >= 0 ? "cc-stat-pill-up" : "cc-stat-pill-down"
                  )}
                >
                  {todayDelta >= 0 ? "+" : ""}
                  {todayDelta} today
                </span>
                <span className="text-meta">vs. yesterday ({yesterdayCount})</span>
              </div>
              <div className="mt-4 border-t border-border-subtle pt-3 text-meta">
                {recordedEventCount} timeline events recorded across visible tickets
              </div>
            </Card>

            <Card>
              <CardHeader>
                <div>
                  <CardTitle>Status breakdown</CardTitle>
                  <CardDescription>Current lifecycle of all tickets</CardDescription>
                </div>
              </CardHeader>
              <DonutChart
                data={statusBreakdown}
                centerValue={String(data.total)}
                centerLabel="tickets"
              />
            </Card>

            <Card>
              <CardHeader>
                <div>
                  <CardTitle>Ticket volume</CardTitle>
                  <CardDescription>Opened per day, last 7 days</CardDescription>
                </div>
              </CardHeader>
              <BarChart data={ticketVolume} />
            </Card>
          </div>

          <div className="cc-card mt-6 overflow-hidden">
            {filteredSessions.length === 0 ? (
              <div className="p-6">
                <EmptyState
                  title="No tickets match these filters."
                  message="Tickets appear here once customer sessions are processed through the pipeline."
                  actionLabel="Refresh"
                  onAction={reload}
                />
              </div>
            ) : (
              <DataTable
                columns={columns}
                rows={filteredSessions}
                rowKey={(session) => session.session_id}
                minWidth="880px"
                expandedRowId={expandedSessionId}
                renderExpanded={(session) => (
                  <div className="px-4 py-4">
                    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                      <h4 className="heading-section text-[13px]">Technical details</h4>
                      <DownloadableLog
                        data={session}
                        filename={`session-${session.session_id}.json`}
                        label="Download session log"
                      />
                    </div>
                    <CodeAsReadableText
                      data={{
                        session_id: session.session_id,
                        lineage_id: session.lineage_id,
                        root_session_id: session.root_session_id,
                        parent_session_id: session.parent_session_id,
                        ancestor_session_ids: session.ancestor_session_ids,
                        lineage_depth: session.lineage_depth,
                        revision: session.revision,
                        tenant_id: session.tenant_id,
                        principal_id: session.principal_id,
                        context_environment: session.context_environment,
                        context_labels: session.context_labels,
                        lifecycle_phase: session.lifecycle_phase,
                        lifecycle_reason: session.lifecycle_reason,
                      }}
                    />
                  </div>
                )}
              />
            )}

            <div className="flex min-h-12 flex-col gap-2 border-t border-border-subtle px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
              <span className="text-meta">
                Showing {filteredSessions.length} of {data.total} tickets
              </span>
              <span className="text-meta">
                Last refreshed {formatRelativeTime(data.fetchedAt)}
              </span>
            </div>
          </div>
        </>
      )}
    </main>
  );
}

function compareSessionsByOpenedAtDesc(left: SessionRecord, right: SessionRecord): number {
  return new Date(right.opened_at).getTime() - new Date(left.opened_at).getTime();
}

function getQueueStatusId(session: SessionRecord): QueueStatusId {
  if (session.lifecycle_phase === "completed") return "completed";
  if (session.lifecycle_phase === "suspended") return "suspended";
  if (session.lifecycle_phase === "failed") return "failed";
  if (session.sequence_head >= 2) return "completed";
  return "initiated";
}

function getQueueStatusMeta(session: SessionRecord): StatusMeta {
  if (session.lifecycle_phase === "completed") return statusMetaByQueueId.completed;
  if (session.lifecycle_phase === "suspended") return statusMetaByQueueId.suspended;
  if (session.lifecycle_phase === "failed") return statusMetaByQueueId.failed;
  if (session.sequence_head >= 2) return timelineReadyMeta;
  if (session.sequence_head >= 0) return openedMeta;
  return { label: session.lifecycle_phase || "Unknown", tone: "neutral", icon: Activity };
}

function buildTicketVolume(sessions: SessionRecord[]): { label: string; value: number }[] {
  const days: { label: string; value: number; dateKey: string }[] = [];
  const now = new Date();
  for (let i = 6; i >= 0; i -= 1) {
    const date = new Date(now);
    date.setDate(now.getDate() - i);
    days.push({
      label: date.toLocaleDateString(undefined, { weekday: "short" }),
      value: 0,
      dateKey: date.toISOString().slice(0, 10),
    });
  }

  for (const session of sessions) {
    const dateKey = session.opened_at.slice(0, 10);
    const day = days.find((entry) => entry.dateKey === dateKey);
    if (day) day.value += 1;
  }

  return days.map(({ label, value }) => ({ label, value }));
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
