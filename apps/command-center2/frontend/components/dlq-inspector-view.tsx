"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  RefreshCw,
  RotateCcw,
  Search,
  XCircle,
} from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-state";
import {
  formatApiError,
  listDeadLetters,
  replayDeadLetter,
  type DeadLetterItem,
  type DeadLetterListResponse,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 50;

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

export function DlqInspectorView() {
  const [data, setData] = useState<DeadLetterListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [queueFilter, setQueueFilter] = useState("");
  const [errorClassInput, setErrorClassInput] = useState("");
  const [errorClassFilter, setErrorClassFilter] = useState("");
  const [offset, setOffset] = useState(0);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [confirmationId, setConfirmationId] = useState<string | null>(null);
  const [replayingId, setReplayingId] = useState<string | null>(null);
  const [replayErrors, setReplayErrors] = useState<Record<string, string>>({});
  const hasLoadedRef = useRef(false);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      setOffset(0);
      setErrorClassFilter(errorClassInput.trim());
    }, 500);
    return () => window.clearTimeout(timeout);
  }, [errorClassInput]);

  const fetchDeadLetters = useCallback(async () => {
    if (hasLoadedRef.current) {
      setIsRefreshing(true);
    } else {
      setIsLoading(true);
    }
    setError(null);

    try {
      const response = await listDeadLetters({
        queue: queueFilter || null,
        error_class: errorClassFilter || null,
        limit: PAGE_SIZE,
        offset,
      });
      hasLoadedRef.current = true;
      setData(response);
    } catch (caught: unknown) {
      setError(formatApiError(caught));
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, [errorClassFilter, offset, queueFilter]);

  useEffect(() => {
    void fetchDeadLetters();
  }, [fetchDeadLetters]);

  const pageSummary = useMemo(() => {
    const total = data?.total ?? 0;
    const count = data?.items.length ?? 0;
    if (total === 0 || count === 0) return "Showing 0 of 0 records";
    const start = offset + 1;
    const end = Math.min(offset + count, total);
    return `Showing ${start}-${end} of ${total} records`;
  }, [data?.items.length, data?.total, offset]);

  const canGoPrevious = offset > 0;
  const canGoNext = data ? offset + PAGE_SIZE < data.total : false;

  const submitReplay = async (item: DeadLetterItem) => {
    setReplayingId(item.id);
    setReplayErrors((current) => {
      const next = { ...current };
      delete next[item.id];
      return next;
    });

    try {
      const response = await replayDeadLetter(item.id);
      setData((current) =>
        current
          ? {
              ...current,
              items: current.items.map((row) =>
                row.id === item.id
                  ? {
                      ...row,
                      replayed: true,
                      replayed_at: response.replayed_at || new Date().toISOString(),
                    }
                  : row
              ),
            }
          : current
      );
      setConfirmationId(null);
    } catch {
      setReplayErrors((current) => ({
        ...current,
        [item.id]: "Replay failed.",
      }));
    } finally {
      setReplayingId(null);
    }
  };

  return (
    <main className="min-w-0 flex-1 overflow-auto bg-canvas p-4 sm:p-6 lg:p-8">
      <div className="mb-2 font-mono text-[11px] uppercase tracking-[0.18em] text-ink-tertiary">
        OPERATIONS · DEAD LETTERS
      </div>
      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h1 className="font-display text-[32px] font-semibold text-ink-primary">
          DLQ Inspector
        </h1>
        <button
          type="button"
          onClick={() => void fetchDeadLetters()}
          className="flex h-11 w-11 items-center justify-center rounded border border-border-subtle bg-surface transition-all duration-160 hover:border-border-defined sm:h-10 sm:w-10"
          aria-label="Refresh dead letter records"
        >
          <RefreshCw
            size={14}
            strokeWidth={1.5}
            className={cn("text-ink-secondary", isRefreshing && "animate-spin")}
          />
        </button>
      </div>

      <div className="mb-4 flex flex-col gap-3 rounded-lg border border-border-subtle bg-surface p-3 md:flex-row md:items-end">
        <label className="flex flex-1 flex-col gap-1">
          <span className="font-technical text-[10px] font-semibold uppercase tracking-[0.16em] text-ink-tertiary">
            Queue
          </span>
          <select
            value={queueFilter}
            onChange={(event) => {
              setQueueFilter(event.target.value);
              setOffset(0);
            }}
            className="h-11 rounded border border-border-subtle bg-surface-raised px-3 text-[13px] text-ink-primary outline-none transition-colors focus:border-border-defined sm:h-10"
          >
            <option value="">All queues</option>
            {QUEUE_NAMES.map((queueName) => (
              <option key={queueName} value={queueName}>
                {QUEUE_LABELS[queueName]}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-1 flex-col gap-1">
          <span className="font-technical text-[10px] font-semibold uppercase tracking-[0.16em] text-ink-tertiary">
            Error Class
          </span>
          <div className="relative">
            <Search
              size={14}
              strokeWidth={1.5}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-tertiary"
            />
            <input
              value={errorClassInput}
              onChange={(event) => setErrorClassInput(event.target.value)}
              placeholder="Filter by error class..."
              className="h-11 w-full rounded border border-border-subtle bg-surface-raised pl-9 pr-3 text-[13px] text-ink-primary placeholder:text-ink-tertiary outline-none transition-colors focus:border-border-defined sm:h-10"
            />
          </div>
        </label>
      </div>

      {isLoading && !data && <LoadingState label="Loading dead letter records..." />}

      {error && !data && !isLoading && (
        <ErrorState
          title="DLQ records unavailable"
          message={error}
          actionLabel="Retry"
          onAction={() => void fetchDeadLetters()}
        />
      )}

      {data && !isLoading && !error && data.items.length === 0 && (
        <EmptyState
          title="No dead letter records found for this tenant."
          message="The dead-letter task table returned no records for the current filters."
          actionLabel="Refresh"
          onAction={() => void fetchDeadLetters()}
        />
      )}

      {data && data.items.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-border-subtle bg-surface">
          {error && (
            <div className="border-b border-warning-amber/30 bg-warning-amber/10 px-4 py-2 text-[13px] text-warning-amber">
              DLQ records unavailable. Showing the last successful page.
            </div>
          )}

          <div className="overflow-x-auto">
            <div className="min-w-[1060px]">
              <div className="grid h-11 grid-cols-[minmax(220px,1fr)_190px_220px_110px_130px_130px_120px] items-center border-b border-border-subtle bg-surface-raised px-3 sm:h-9">
                <TableHeader>Task Name</TableHeader>
                <TableHeader>Queue</TableHeader>
                <TableHeader>Error Class</TableHeader>
                <TableHeader>Attempts</TableHeader>
                <TableHeader>Age</TableHeader>
                <TableHeader>Status</TableHeader>
                <TableHeader>Action</TableHeader>
              </div>

              {data.items.map((item, index) => (
                <DeadLetterRow
                  key={item.id}
                  item={item}
                  isOdd={index % 2 === 1}
                  isExpanded={expandedId === item.id}
                  confirmationOpen={confirmationId === item.id}
                  isReplaying={replayingId === item.id}
                  replayError={replayErrors[item.id] ?? null}
                  onToggle={() =>
                    setExpandedId((current) => (current === item.id ? null : item.id))
                  }
                  onRequestReplay={() => {
                    setExpandedId(item.id);
                    setConfirmationId(item.id);
                  }}
                  onCancelReplay={() => setConfirmationId(null)}
                  onConfirmReplay={() => void submitReplay(item)}
                />
              ))}
            </div>
          </div>

          <div className="flex min-h-12 flex-col gap-3 border-t border-border-subtle px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <span className="text-[12px] text-ink-tertiary">{pageSummary}</span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={!canGoPrevious}
                onClick={() => setOffset((current) => Math.max(0, current - PAGE_SIZE))}
                className="h-10 rounded border border-border-subtle px-3 text-[12px] text-ink-secondary transition-colors hover:border-border-defined hover:text-ink-primary disabled:cursor-not-allowed disabled:opacity-40"
              >
                Previous
              </button>
              <button
                type="button"
                disabled={!canGoNext}
                onClick={() => setOffset((current) => current + PAGE_SIZE)}
                className="h-10 rounded border border-border-subtle px-3 text-[12px] text-ink-secondary transition-colors hover:border-border-defined hover:text-ink-primary disabled:cursor-not-allowed disabled:opacity-40"
              >
                Next
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}

function DeadLetterRow({
  item,
  isOdd,
  isExpanded,
  confirmationOpen,
  isReplaying,
  replayError,
  onToggle,
  onRequestReplay,
  onCancelReplay,
  onConfirmReplay,
}: {
  item: DeadLetterItem;
  isOdd: boolean;
  isExpanded: boolean;
  confirmationOpen: boolean;
  isReplaying: boolean;
  replayError: string | null;
  onToggle: () => void;
  onRequestReplay: () => void;
  onCancelReplay: () => void;
  onConfirmReplay: () => void;
}) {
  const ToggleIcon = isExpanded ? ChevronUp : ChevronDown;

  return (
    <div className={cn(isOdd ? "bg-canvas/50" : "bg-surface", "border-b border-border-subtle last:border-b-0")}>
      <div
        role="button"
        tabIndex={0}
        onClick={onToggle}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onToggle();
          }
        }}
        className="grid min-h-16 cursor-pointer grid-cols-[minmax(220px,1fr)_190px_220px_110px_130px_130px_120px] items-center px-3 transition-colors duration-160 hover:bg-[var(--surface-sunken)]"
      >
        <div className="min-w-0 px-2">
          <span className="block truncate text-[13px] font-medium text-ink-primary">
            {item.task_name}
          </span>
          <span className="block truncate font-technical text-[11px] text-ink-tertiary">
            {shortId(item.id)}
          </span>
        </div>
        <DataCell value={formatQueueName(item.queue)} muted={item.queue === null} />
        <DataCell value={item.error_class} />
        <DataCell value={String(item.attempt_count)} />
        <DataCell value={formatCreatedAge(item.created_at)} />
        <div className="px-2">
          <ReplayStatusBadge replayed={item.replayed} />
        </div>
        <div className="flex items-center justify-end gap-2 px-2">
          {!item.replayed && (
            <button
              type="button"
              disabled={isReplaying}
              onClick={(event) => {
                event.stopPropagation();
                onRequestReplay();
              }}
              className="inline-flex h-9 items-center gap-2 rounded border border-gold-primary/40 px-3 font-technical text-[10px] uppercase tracking-[0.12em] text-gold-primary transition-colors hover:bg-gold-primary/10 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <RotateCcw size={12} strokeWidth={1.5} />
              {isReplaying ? "Replaying" : "Replay"}
            </button>
          )}
          <ToggleIcon size={14} strokeWidth={1.5} className="text-ink-tertiary" />
        </div>
      </div>

      {isExpanded && (
        <div className="border-t border-border-subtle bg-surface-sunken/60 px-5 py-4">
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <section>
              <div className="mb-1 font-technical text-[10px] font-semibold uppercase tracking-[0.16em] text-ink-tertiary">
                Error Message
              </div>
              <p className="break-words text-[13px] leading-relaxed text-ink-secondary">
                {item.error_message || "No error message recorded."}
              </p>
            </section>
            <section>
              <div className="mb-1 font-technical text-[10px] font-semibold uppercase tracking-[0.16em] text-ink-tertiary">
                Task Payload
              </div>
              <pre className="max-h-[260px] overflow-auto rounded border border-border-subtle bg-surface px-3 py-2 font-mono text-[12px] leading-relaxed text-ink-secondary">
                {JSON.stringify(item.task_payload, null, 2)}
              </pre>
            </section>
          </div>

          {confirmationOpen && !item.replayed && (
            <div className="mt-4 rounded border border-warning-amber/30 bg-warning-amber/10 px-3 py-3">
              <p className="text-[13px] text-warning-amber">
                Replay this task? It will be republished to its queue.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={isReplaying}
                  onClick={onConfirmReplay}
                  className="h-10 rounded border border-gold-primary/40 px-3 text-[12px] font-medium text-gold-primary transition-colors hover:bg-gold-primary/10 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Confirm
                </button>
                <button
                  type="button"
                  disabled={isReplaying}
                  onClick={onCancelReplay}
                  className="h-10 rounded border border-border-subtle px-3 text-[12px] text-ink-secondary transition-colors hover:border-border-defined hover:text-ink-primary disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {replayError && (
            <div className="mt-3 rounded border border-red-alert/20 bg-red-alert/10 px-3 py-2 text-[13px] text-red-alert">
              {replayError}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ReplayStatusBadge({ replayed }: { replayed: boolean }) {
  const Icon = replayed ? CheckCircle2 : XCircle;
  return (
    <div
      className={cn(
        "inline-flex items-center gap-1.5 rounded border px-2 py-1",
        replayed
          ? "border-green-success/20 bg-green-success/10"
          : "border-red-alert/20 bg-red-alert/10"
      )}
    >
      <Icon
        size={12}
        strokeWidth={1.5}
        className={replayed ? "text-green-success" : "text-red-alert"}
      />
      <span
        className={cn(
          "font-technical text-[10px] font-medium tracking-wider",
          replayed ? "text-green-success" : "text-red-alert"
        )}
      >
        {replayed ? "Replayed" : "Pending"}
      </span>
    </div>
  );
}

function DataCell({ value, muted = false }: { value: string; muted?: boolean }) {
  return (
    <div className="min-w-0 px-2">
      <span
        className={cn(
          "block truncate font-technical text-[12px] tabular-nums",
          muted ? "text-ink-tertiary" : "text-ink-secondary"
        )}
        title={value}
      >
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

function formatQueueName(queue: string | null): string {
  if (queue === null) return "Unknown";
  return QUEUE_LABELS[queue] ?? queue;
}

function formatCreatedAge(value: string): string {
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return "unknown";
  return formatAge(Math.max(0, (Date.now() - timestamp) / 1000));
}

function formatAge(seconds: number | null): string {
  if (seconds === null) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${Math.round(seconds / 3600)}h`;
}

function shortId(value: string): string {
  return value.length <= 13 ? value : `${value.slice(0, 8)}...${value.slice(-4)}`;
}
