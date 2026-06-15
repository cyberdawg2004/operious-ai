"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  CircleHelp,
  RefreshCw,
  XCircle,
} from "lucide-react";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { BarChart, DonutChart } from "@/components/ui/chart";
import { ErrorState, LoadingState } from "@/components/data-state";
import {
  formatApiError,
  getQueueStatus,
  type QueueDepthItem,
  type QueueStatusResponse,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const REFRESH_INTERVAL_MS = 30_000;

const QUEUE_LABELS: Record<string, string> = {
  "diagnostic.high": "Diagnostic (High Priority)",
  "diagnostic.normal": "Diagnostic (Normal)",
  "diagnostic.retry": "Diagnostic (Retry)",
  escalation: "Escalation",
  supervisor: "Supervisor",
  qa: "Quality Assurance",
  sop_intelligence: "SOP Intelligence",
  knowledge_indexing: "Knowledge Indexing",
  webhook_maintenance: "Webhook Maintenance",
  dead_letter: "Dead Letter",
  "ingress.email": "Email Ingress",
  "ingress.whatsapp": "WhatsApp Ingress",
  "ingress.shopify": "Shopify Ingress",
  "ingress.voice": "Voice Ingress",
};

const QUEUE_NAMES = Object.keys(QUEUE_LABELS);

type QueueStatus = QueueDepthItem["status"];

const statusConfig: Record<
  QueueStatus,
  {
    label: string;
    icon: typeof CheckCircle2;
    color: string;
    bgColor: string;
    borderColor: string;
  }
> = {
  ok: {
    label: "OK",
    icon: CheckCircle2,
    color: "text-green-success",
    bgColor: "bg-green-success/10",
    borderColor: "border-green-success/20",
  },
  warn: {
    label: "Warn",
    icon: AlertTriangle,
    color: "text-warning-amber",
    bgColor: "bg-warning-amber/10",
    borderColor: "border-warning-amber/25",
  },
  critical: {
    label: "Critical",
    icon: XCircle,
    color: "text-red-alert",
    bgColor: "bg-red-alert/10",
    borderColor: "border-red-alert/20",
  },
  unknown: {
    label: "Unknown",
    icon: CircleHelp,
    color: "text-ink-tertiary",
    bgColor: "bg-surface-sunken",
    borderColor: "border-border-subtle",
  },
};

const statusChartColors: Record<QueueStatus, string> = {
  ok: "var(--chart-green)",
  warn: "var(--chart-amber)",
  critical: "var(--chart-pink)",
  unknown: "var(--chart-blue-soft)",
};

export function QueueStatusView() {
  const [data, setData] = useState<QueueStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const hasLoadedRef = useRef(false);

  const fetchQueueStatus = useCallback(async () => {
    if (hasLoadedRef.current) {
      setIsRefreshing(true);
    } else {
      setIsLoading(true);
    }
    setError(null);

    try {
      const response = await getQueueStatus();
      hasLoadedRef.current = true;
      setData(response);
    } catch (caught: unknown) {
      setError(formatApiError(caught));
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, []);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      void fetchQueueStatus();
    }, 0);
    const interval = window.setInterval(() => {
      void fetchQueueStatus();
    }, REFRESH_INTERVAL_MS);
    return () => {
      window.clearTimeout(timeout);
      window.clearInterval(interval);
    };
  }, [fetchQueueStatus]);

  const rows = useMemo(
    () =>
      QUEUE_NAMES.map((queueName) => {
        const item = data?.queues[queueName];
        return (
          item ?? {
            queue_name: queueName,
            depth: 0,
            oldest_age_seconds: null,
            status: "unknown" as const,
            error: data ? "Missing from queue status response" : null,
          }
        );
      }),
    [data]
  );

  const statusBreakdown = useMemo(() => {
    const counts: Record<QueueStatus, number> = { ok: 0, warn: 0, critical: 0, unknown: 0 };
    for (const row of rows) {
      counts[row.status] += 1;
    }
    return (Object.keys(counts) as QueueStatus[])
      .filter((status) => counts[status] > 0)
      .map((status) => ({
        label: statusConfig[status].label,
        value: counts[status],
        color: statusChartColors[status],
      }));
  }, [rows]);

  const depthByQueue = useMemo(
    () =>
      [...rows]
        .sort((a, b) => b.depth - a.depth)
        .slice(0, 6)
        .map((row) => ({
          label: QUEUE_LABELS[row.queue_name]?.replace(/ \(.*\)/, "") ?? row.queue_name,
          value: row.depth,
          color: statusChartColors[row.status],
        })),
    [rows]
  );

  return (
    <main className="min-w-0 flex-1 overflow-auto bg-canvas p-4 sm:p-6 lg:p-8">
      <div className="mb-2 font-mono text-[11px] uppercase tracking-[0.18em] text-ink-tertiary">
        OPERATIONS · QUEUE STATUS
      </div>
      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h1 className="font-display text-[32px] font-semibold text-ink-primary">
          Queue Status
        </h1>
        <button
          type="button"
          onClick={() => void fetchQueueStatus()}
          className="flex h-11 w-11 items-center justify-center rounded border border-border-subtle bg-surface transition-all duration-160 hover:border-border-defined sm:h-10 sm:w-10"
          aria-label="Refresh queue status"
        >
          <RefreshCw
            size={14}
            strokeWidth={1.5}
            className={cn("text-ink-secondary", isRefreshing && "animate-spin")}
          />
        </button>
      </div>

      {isLoading && !data && <LoadingState label="Loading queue status..." />}

      {error && !data && !isLoading && (
        <ErrorState
          title="Queue data unavailable"
          message={error}
          actionLabel="Retry"
          onAction={() => void fetchQueueStatus()}
        />
      )}

      {data && (
        <>
          {error && (
            <div className="mb-4 rounded border border-warning-amber/30 bg-warning-amber/10 px-3 py-2 text-[13px] text-warning-amber">
              Queue data unavailable. Showing the last successful snapshot.
            </div>
          )}

          <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)]">
            <Card>
              <CardHeader>
                <div>
                  <CardTitle>Queue health</CardTitle>
                  <CardDescription>Status across all monitored queues</CardDescription>
                </div>
              </CardHeader>
              <DonutChart
                data={statusBreakdown}
                centerValue={String(rows.length)}
                centerLabel="queues"
              />
            </Card>

            <Card>
              <CardHeader>
                <div>
                  <CardTitle>Deepest queues</CardTitle>
                  <CardDescription>Top queues by pending depth</CardDescription>
                </div>
              </CardHeader>
              <BarChart data={depthByQueue} />
            </Card>
          </div>

          <div className="overflow-hidden rounded-lg border border-border-subtle bg-surface">
            <div className="overflow-x-auto">
              <div className="min-w-[760px]">
                <div className="grid h-11 grid-cols-[minmax(260px,1fr)_120px_150px_140px] items-center border-b border-border-subtle bg-surface-raised px-3 sm:h-9">
                  <TableHeader>Queue Name</TableHeader>
                  <TableHeader>Depth</TableHeader>
                  <TableHeader>Status</TableHeader>
                  <TableHeader>Age</TableHeader>
                </div>
                {rows.map((queue, index) => (
                  <QueueRow key={queue.queue_name} queue={queue} isOdd={index % 2 === 1} />
                ))}
              </div>
            </div>
            <div className="flex min-h-12 flex-col gap-2 border-t border-border-subtle px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
              <span className="text-[12px] text-ink-tertiary">
                Showing {rows.length} queues
              </span>
              <span className="font-technical text-[11px] uppercase tracking-[0.12em] text-ink-tertiary">
                Snapshot {formatSnapshotTime(data.snapshot_at)}
              </span>
            </div>
          </div>
        </>
      )}
    </main>
  );
}

function QueueRow({ queue, isOdd }: { queue: QueueDepthItem; isOdd: boolean }) {
  return (
    <div
      className={cn(
        "grid min-h-14 grid-cols-[minmax(260px,1fr)_120px_150px_140px] items-center border-b border-border-subtle px-3 last:border-b-0 sm:min-h-11",
        isOdd ? "bg-canvas/50" : "bg-surface"
      )}
    >
      <div className="min-w-0 px-2">
        <span className="block truncate text-[13px] font-medium text-ink-primary">
          {QUEUE_LABELS[queue.queue_name] ?? queue.queue_name}
        </span>
        <span className="block truncate font-technical text-[11px] text-ink-tertiary">
          {queue.queue_name}
        </span>
      </div>
      <DataCell value={String(queue.depth)} />
      <div className="px-2">
        <StatusBadge status={queue.status} />
      </div>
      <div className="px-2">
        <span
          className="block truncate font-technical text-[12px] tabular-nums text-ink-secondary"
          title={queue.error ?? undefined}
        >
          {formatAge(queue.oldest_age_seconds)}
        </span>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: QueueStatus }) {
  const config = statusConfig[status] ?? statusConfig.unknown;
  const Icon = config.icon;

  return (
    <div
      className={cn(
        "inline-flex items-center gap-1.5 rounded border px-2 py-1",
        config.bgColor,
        config.borderColor
      )}
    >
      <Icon size={12} strokeWidth={1.5} className={config.color} />
      <span className={cn("font-technical text-[10px] font-medium tracking-wider", config.color)}>
        {config.label}
      </span>
    </div>
  );
}

function DataCell({ value }: { value: string }) {
  return (
    <div className="px-2">
      <span className="block truncate font-technical text-[12px] tabular-nums text-ink-secondary">
        {value}
      </span>
    </div>
  );
}

function TableHeader({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-2 font-technical text-[10px] font-semibold uppercase tracking-[0.16em] text-ink-tertiary">
      {children}
    </div>
  );
}

function formatAge(seconds: number | null): string {
  if (seconds === null) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${Math.round(seconds / 3600)}h`;
}

function formatSnapshotTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "unknown";
  return date.toISOString();
}
