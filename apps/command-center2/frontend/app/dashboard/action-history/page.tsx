"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckCircle2, RefreshCw, ShieldAlert, ShieldX } from "lucide-react";
import {
  formatApiError,
  listActionApprovals,
  listEscalations,
  type ActionApprovalSummary,
  type EscalationRecord,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-state";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TabId = "approved" | "denied" | "escalated";

type HistoryRow = {
  id: string;
  time: string;
  rawTimestamp: string; // ISO date string for 24h filtering
  session: string;
  decision: string;
  reason: string;
  outcome: string;
  outcomeTone: "ok" | "warn" | "neutral";
};

// ---------------------------------------------------------------------------
// Data helpers
// ---------------------------------------------------------------------------

function relativeTime(value: string): string {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return "—";
  const diffMs = Date.now() - timestamp;
  const seconds = Math.max(0, Math.floor(diffMs / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function shortSession(value: string): string {
  if (!value) return "—";
  // Show up to 12 chars then ellipsis if longer
  return value.length > 12 ? `${value.slice(0, 10)}…` : value;
}

function toolLabel(toolName: string): string {
  const labels: Record<string, string> = {
    "warranty.claim": "Warranty claim",
    "replacement.order": "Replacement order",
    "refund.request": "Refund request",
    "warehouse.repair.report": "Repair report",
  };
  return (
    labels[toolName] ??
    toolName
      .replace(/[._]/g, " ")
      .replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

function outcomeTone(status: string): "ok" | "warn" | "neutral" {
  if (status === "approved" || status === "resolved") return "ok";
  if (status === "pending" || status === "escalated") return "warn";
  return "neutral";
}

function outcomeToneClass(tone: "ok" | "warn" | "neutral"): string {
  if (tone === "ok") return "border-green-success/40 text-green-success";
  if (tone === "warn") return "border-gold-primary/40 text-gold-primary";
  return "border-border-subtle text-ink-secondary";
}

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------

const CUTOFF_24H_MS = 24 * 60 * 60 * 1000;

function isWithin24h(isoDate: string): boolean {
  const ts = Date.parse(isoDate);
  return Number.isFinite(ts) && Date.now() - ts <= CUTOFF_24H_MS;
}

async function fetchApproved(): Promise<HistoryRow[]> {
  const items = await listActionApprovals({ status: "approved", limit: 50, offset: 0 });
  return items.map((item: ActionApprovalSummary): HistoryRow => ({
    id: item.approval_id,
    time: relativeTime(item.resolved_at ?? item.requested_at),
    rawTimestamp: item.resolved_at ?? item.requested_at,
    session: shortSession(item.session_id),
    decision: toolLabel(item.tool_name),
    reason: item.resolution_note ?? "Auto-approved by governance policy",
    outcome: item.status,
    outcomeTone: outcomeTone(item.status),
  }));
}

async function fetchDenied(): Promise<HistoryRow[]> {
  // The denied endpoint is the same actions endpoint with status=denied.
  // If this returns no items, it gracefully shows an empty state.
  const items = await listActionApprovals({ status: "denied", limit: 50, offset: 0 });
  return items.map((item: ActionApprovalSummary): HistoryRow => ({
    id: item.approval_id,
    time: relativeTime(item.resolved_at ?? item.requested_at),
    rawTimestamp: item.resolved_at ?? item.requested_at,
    session: shortSession(item.session_id),
    decision: toolLabel(item.tool_name),
    reason: item.resolution_note ?? "Denied by governance rule",
    outcome: item.status,
    outcomeTone: "neutral",
  }));
}

async function fetchEscalated(): Promise<HistoryRow[]> {
  const page = await listEscalations({ status: "pending", limit: 50, offset: 0 });
  // Also grab reviewed escalations so we show history, not just the pending queue.
  const [resolvedResult] = await Promise.allSettled([
    listEscalations({ status: "reviewed", limit: 50, offset: 0 }),
  ]);
  const resolvedItems =
    resolvedResult.status === "fulfilled" ? resolvedResult.value.items : [];
  const all: EscalationRecord[] = [...page.items, ...resolvedItems];
  return all.map((esc: EscalationRecord): HistoryRow => ({
    id: esc.escalation_id,
    time: relativeTime(esc.created_at),
    rawTimestamp: esc.created_at,
    session: shortSession(esc.session_id),
    decision: `Escalation — ${esc.handoff_kind}`,
    reason: esc.reason,
    outcome: esc.status,
    outcomeTone: outcomeTone(esc.status),
  }));
}

// ---------------------------------------------------------------------------
// Stat tile
// ---------------------------------------------------------------------------

function StatTile({
  label,
  value,
  loading,
  tone = "neutral",
}: {
  label: string;
  value: number | null;
  loading: boolean;
  tone?: "ok" | "warn" | "neutral";
}) {
  const valueClass =
    tone === "ok"
      ? "text-green-success"
      : tone === "warn"
        ? "text-gold-primary"
        : "text-ink-primary";

  return (
    <div className="rounded-lg border border-border-subtle bg-surface p-4 shadow-sm">
      <p className="font-technical text-[10px] uppercase tracking-[0.14em] text-ink-tertiary">
        {label}
      </p>
      <p
        className={cn(
          "mt-2 text-[28px] font-semibold leading-none",
          loading ? "text-ink-tertiary" : valueClass
        )}
      >
        {loading ? "…" : value === null ? "—" : String(value)}
      </p>
      <p className="mt-1 font-technical text-[10px] text-ink-tertiary">Last 24 hours</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Table
// ---------------------------------------------------------------------------

const COL_HEADERS: { key: string; label: string; className: string }[] = [
  { key: "time", label: "Time", className: "w-[90px] shrink-0" },
  { key: "session", label: "Session", className: "w-[100px] shrink-0 hidden sm:block" },
  { key: "decision", label: "Action / Decision", className: "flex-1 min-w-0" },
  { key: "reason", label: "Reason", className: "flex-1 min-w-0 hidden lg:block" },
  { key: "outcome", label: "Outcome", className: "w-[110px] shrink-0 text-right" },
];

function HistoryTable({ rows }: { rows: HistoryRow[] }) {
  return (
    <div className="overflow-hidden rounded-lg border border-border-subtle">
      {/* Header */}
      <div className="hidden border-b border-border-subtle bg-surface-raised px-4 py-2 sm:flex">
        {COL_HEADERS.map((col) => (
          <div
            key={col.key}
            className={cn(
              "font-technical text-[10px] uppercase tracking-[0.14em] text-ink-tertiary",
              col.className
            )}
          >
            {col.label}
          </div>
        ))}
      </div>
      {/* Rows */}
      <div className="divide-y divide-border-subtle">
        {rows.map((row) => (
          <div
            key={row.id}
            className="flex flex-col gap-1 bg-surface px-4 py-3 transition-colors hover:bg-surface-raised sm:flex-row sm:items-center sm:gap-0"
          >
            {/* Time */}
            <div className="w-[90px] shrink-0">
              <span className="font-technical text-[12px] text-ink-tertiary">{row.time}</span>
            </div>
            {/* Session */}
            <div className="hidden w-[100px] shrink-0 sm:block">
              <span className="font-technical text-[12px] text-ink-secondary">{row.session}</span>
            </div>
            {/* Decision */}
            <div className="min-w-0 flex-1 sm:pr-4">
              <span className="block truncate text-[13px] font-medium text-ink-primary">
                {row.decision}
              </span>
              {/* Show session inline on mobile */}
              <span className="mt-0.5 block font-technical text-[11px] text-ink-tertiary sm:hidden">
                {row.session}
              </span>
            </div>
            {/* Reason */}
            <div className="hidden min-w-0 flex-1 pr-4 lg:block">
              <span className="block truncate text-[13px] text-ink-secondary">{row.reason}</span>
            </div>
            {/* Outcome badge */}
            <div className="w-auto shrink-0 sm:w-[110px] sm:text-right">
              <span
                className={cn(
                  "inline-block rounded border bg-surface-raised px-2 py-1 font-technical text-[10px] uppercase tracking-[0.10em]",
                  outcomeToneClass(row.outcomeTone)
                )}
              >
                {row.outcome}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab button
// ---------------------------------------------------------------------------

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex h-9 items-center gap-2 rounded-md border px-4 font-technical text-[11px] uppercase tracking-[0.10em] transition-colors",
        active
          ? "border-gold-primary bg-surface text-ink-primary"
          : "border-border-subtle bg-surface text-ink-secondary hover:border-border-defined hover:text-ink-primary"
      )}
    >
      {children}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function ActionHistoryPage() {
  const [activeTab, setActiveTab] = useState<TabId>("approved");
  const [rows, setRows] = useState<HistoryRow[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);

  // Stat counts
  const [approvedCount, setApprovedCount] = useState<number | null>(null);
  const [deniedCount, setDeniedCount] = useState<number | null>(null);
  const [escalatedCount, setEscalatedCount] = useState<number | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);

  // Load stats once (all three in parallel) on mount
  const loadStats = useCallback(async () => {
    setStatsLoading(true);
    const [approvedResult, deniedResult, escalatedResult] = await Promise.allSettled([
      fetchApproved(),
      fetchDenied(),
      fetchEscalated(),
    ]);
    if (approvedResult.status === "fulfilled") {
      setApprovedCount(
        approvedResult.value.filter((r) => isWithin24h(r.rawTimestamp)).length
      );
    }
    if (deniedResult.status === "fulfilled") {
      setDeniedCount(
        deniedResult.value.filter((r) => isWithin24h(r.rawTimestamp)).length
      );
    }
    if (escalatedResult.status === "fulfilled") {
      setEscalatedCount(
        escalatedResult.value.filter((r) => isWithin24h(r.rawTimestamp)).length
      );
    }
    setStatsLoading(false);
  }, []);

  useEffect(() => {
    void loadStats();
  }, [loadStats]);

  // Load the active tab data
  const loadTab = useCallback(
    async (tab: TabId, isBackground = false) => {
      if (!isBackground) {
        setIsLoading(true);
        setError(null);
      } else {
        setIsRefreshing(true);
      }
      try {
        let fetched: HistoryRow[];
        if (tab === "approved") {
          fetched = await fetchApproved();
        } else if (tab === "denied") {
          fetched = await fetchDenied();
        } else {
          fetched = await fetchEscalated();
        }
        setRows(fetched);
        setError(null);
      } catch (caught: unknown) {
        setError(formatApiError(caught));
      } finally {
        setIsLoading(false);
        setIsRefreshing(false);
      }
    },
    []
  );

  useEffect(() => {
    void loadTab(activeTab);
    const interval = window.setInterval(() => void loadTab(activeTab, true), 30_000);
    return () => window.clearInterval(interval);
  }, [activeTab, loadTab]);

  const emptyLabel = useMemo(() => {
    if (activeTab === "approved") return "approved";
    if (activeTab === "denied") return "denied";
    return "escalated";
  }, [activeTab]);

  return (
    <main className="min-w-0 flex-1 overflow-auto bg-canvas px-4 py-5 sm:px-6 lg:px-12 lg:py-8">
      {/* Page header */}
      <div className="mb-2 font-mono text-[11px] uppercase tracking-[0.18em] text-ink-tertiary">
        COMMAND CENTER · ACTION HISTORY
      </div>
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="font-display text-[28px] font-semibold leading-tight text-ink-primary sm:text-[32px]">
            Action History
          </h1>
          <p className="mt-1 text-[13px] text-ink-secondary">
            How the AI has been handling customer requests
          </p>
        </div>
        <button
          type="button"
          onClick={() => void loadTab(activeTab, true)}
          className="flex h-10 w-10 items-center justify-center self-start rounded-md border border-border-subtle bg-surface transition-all duration-150 hover:border-border-defined sm:self-auto"
          aria-label="Refresh action history"
        >
          <RefreshCw
            size={14}
            strokeWidth={1.6}
            className={cn("text-ink-secondary", isRefreshing && "animate-spin")}
          />
        </button>
      </div>

      {/* KPI stat tiles */}
      <section className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatTile
          label="Total Approved"
          value={approvedCount}
          loading={statsLoading}
          tone="ok"
        />
        <StatTile
          label="Total Denied"
          value={deniedCount}
          loading={statsLoading}
          tone="neutral"
        />
        <StatTile
          label="Total Escalated"
          value={escalatedCount}
          loading={statsLoading}
          tone="warn"
        />
      </section>

      {/* Tabs */}
      <div className="mb-4 flex flex-wrap gap-2">
        <TabButton active={activeTab === "approved"} onClick={() => setActiveTab("approved")}>
          <CheckCircle2 className="h-3.5 w-3.5 text-green-success" strokeWidth={1.8} />
          Approved
        </TabButton>
        <TabButton active={activeTab === "denied"} onClick={() => setActiveTab("denied")}>
          <ShieldX className="h-3.5 w-3.5 text-ink-tertiary" strokeWidth={1.8} />
          Denied
        </TabButton>
        <TabButton active={activeTab === "escalated"} onClick={() => setActiveTab("escalated")}>
          <ShieldAlert className="h-3.5 w-3.5 text-gold-primary" strokeWidth={1.8} />
          Escalated
        </TabButton>
      </div>

      {/* Tab content */}
      {isLoading && <LoadingState label={`Loading ${emptyLabel} actions…`} />}

      {!isLoading && error && (
        <ErrorState
          title="Action history unavailable"
          message={error}
          actionLabel="Retry"
          onAction={() => void loadTab(activeTab)}
        />
      )}

      {!isLoading && !error && rows.length === 0 && (
        <EmptyState
          title={`No ${emptyLabel} actions yet`}
          message={`When the AI ${emptyLabel === "approved" ? "approves" : emptyLabel === "denied" ? "denies" : "escalates"} actions, they will appear here.`}
          actionLabel="Refresh"
          onAction={() => void loadTab(activeTab)}
        />
      )}

      {!isLoading && !error && rows.length > 0 && <HistoryTable rows={rows} />}
    </main>
  );
}

