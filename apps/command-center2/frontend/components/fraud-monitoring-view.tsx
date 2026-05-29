"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  RefreshCw,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import { ErrorState, LoadingState } from "@/components/data-state";
import {
  formatApiError,
  listSemanticCircuitEvents,
  listSemanticCircuitStates,
  listSemanticQuarantine,
  releaseSemanticQuarantine,
  type SemanticCircuitEvent,
  type SemanticCircuitState,
  type SemanticQuarantineItem,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type ReleaseVerdict = "false_positive" | "fraud_confirmed";

const STATE_BADGES: Record<SemanticCircuitState["state"], string> = {
  CLOSED: "bg-green-100 text-green-800",
  TRIPPED: "bg-red-100 text-red-800",
  RESET: "bg-gray-100 text-gray-600",
};

export function FraudMonitoringView() {
  return (
    <main className="min-w-0 flex-1 overflow-auto bg-canvas p-4 sm:p-6 lg:p-8">
      <div className="mb-2 font-mono text-[11px] uppercase tracking-[0.18em] text-ink-tertiary">
        OPERATIONS / FRAUD
      </div>
      <div className="mb-5 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="font-display text-[32px] font-semibold text-ink-primary">
            Fraud Monitoring
          </h1>
        </div>
      </div>

      <div className="space-y-6">
        <FraudCircuitStates />
        <QuarantineInspector />
        <FraudEventLog />
      </div>
    </main>
  );
}

function FraudCircuitStates() {
  const [states, setStates] = useState<SemanticCircuitState[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const hasLoadedRef = useRef(false);

  const fetchStates = useCallback(async () => {
    if (hasLoadedRef.current) {
      setIsRefreshing(true);
    } else {
      setIsLoading(true);
    }
    setError(null);
    try {
      const response = await listSemanticCircuitStates();
      hasLoadedRef.current = true;
      setStates(response);
    } catch (caught: unknown) {
      setError(formatApiError(caught));
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void fetchStates();
    const interval = window.setInterval(() => void fetchStates(), 15_000);
    return () => window.clearInterval(interval);
  }, [fetchStates]);

  const allHealthy = (states ?? []).every((state) => state.state !== "TRIPPED");

  return (
    <section>
      <SectionHeader
        eyebrow="LIVE CIRCUITS"
        title="Circuit Breaker States"
        isRefreshing={isRefreshing}
        onRefresh={() => void fetchStates()}
      />

      {!isLoading && !error && allHealthy && (
        <div className="mb-3 flex items-center gap-2 rounded border border-green-200 bg-green-100 px-3 py-2 text-[13px] font-medium text-green-800">
          <CheckCircle2 className="h-4 w-4" strokeWidth={1.7} />
          All circuits healthy
        </div>
      )}

      {isLoading && !states && <LoadingState label="Loading circuit states..." />}

      {error && !states && !isLoading && (
        <ErrorState
          title="Circuit states unavailable"
          message={error}
          actionLabel="Retry"
          onAction={() => void fetchStates()}
        />
      )}

      {states && (
        <div className="overflow-hidden rounded-lg border border-border-subtle bg-surface">
          {error && (
            <div className="border-b border-warning-amber/30 bg-warning-amber/10 px-4 py-2 text-[13px] text-warning-amber">
              Circuit states unavailable. Showing the last successful snapshot.
            </div>
          )}
          <div className="overflow-x-auto">
            <div className="min-w-[780px]">
              <div className="grid h-10 grid-cols-[minmax(180px,1fr)_140px_140px_180px_140px] items-center border-b border-border-subtle bg-surface-raised px-3">
                <TableHeader>Channel</TableHeader>
                <TableHeader>State</TableHeader>
                <TableHeader>Cluster Size</TableHeader>
                <TableHeader>Last Tripped</TableHeader>
                <TableHeader>Window</TableHeader>
              </div>
              {states.length === 0 ? (
                <div className="px-3 py-5 text-[13px] text-ink-secondary">
                  No circuit events recorded.
                </div>
              ) : (
                states.map((state, index) => (
                  <div
                    key={state.channel}
                    className={cn(
                      "grid min-h-12 grid-cols-[minmax(180px,1fr)_140px_140px_180px_140px] items-center px-3 text-[13px]",
                      index % 2 === 1 && "bg-surface-raised/45"
                    )}
                  >
                    <div className="truncate font-medium text-ink-primary">
                      {state.channel}
                    </div>
                    <div>
                      <StateBadge state={state.state} />
                    </div>
                    <div className="text-ink-secondary">
                      {state.cluster_size ?? "-"}
                    </div>
                    <div className="text-ink-secondary">
                      {state.state === "TRIPPED"
                        ? formatRelativeTime(state.occurred_at)
                        : "-"}
                    </div>
                    <div className="text-ink-secondary">
                      {formatWindow(state.window_seconds)}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function QuarantineInspector() {
  const [records, setRecords] = useState<SemanticQuarantineItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [payloadExpandedId, setPayloadExpandedId] = useState<string | null>(null);
  const [pendingRelease, setPendingRelease] = useState<{
    id: string;
    verdict: ReleaseVerdict;
  } | null>(null);
  const [note, setNote] = useState("");
  const [releaseError, setReleaseError] = useState<string | null>(null);
  const [isReleasing, setIsReleasing] = useState(false);
  const hasLoadedRef = useRef(false);

  const fetchRecords = useCallback(async () => {
    if (hasLoadedRef.current) {
      setIsRefreshing(true);
    } else {
      setIsLoading(true);
    }
    setError(null);
    try {
      const response = await listSemanticQuarantine({
        status: "pending",
        limit: 50,
      });
      hasLoadedRef.current = true;
      setRecords(response);
    } catch (caught: unknown) {
      setError(formatApiError(caught));
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void fetchRecords();
    const interval = window.setInterval(() => void fetchRecords(), 30_000);
    return () => window.clearInterval(interval);
  }, [fetchRecords]);

  const selectedRecord = useMemo(
    () =>
      pendingRelease && records
        ? records.find((record) => record.quarantine_id === pendingRelease.id)
        : null,
    [pendingRelease, records]
  );

  const submitRelease = async () => {
    if (!pendingRelease) return;
    setIsReleasing(true);
    setReleaseError(null);
    try {
      await releaseSemanticQuarantine(pendingRelease.id, {
        verdict: pendingRelease.verdict,
        note: note.trim() || null,
      });
      setPendingRelease(null);
      setNote("");
      await fetchRecords();
    } catch (caught: unknown) {
      setReleaseError(formatApiError(caught));
    } finally {
      setIsReleasing(false);
    }
  };

  return (
    <section>
      <SectionHeader
        eyebrow="QUARANTINE"
        title="Quarantine Cluster Inspector"
        isRefreshing={isRefreshing}
        onRefresh={() => void fetchRecords()}
      />

      {isLoading && !records && <LoadingState label="Loading quarantine records..." />}

      {error && !records && !isLoading && (
        <ErrorState
          title="Quarantine unavailable"
          message={error}
          actionLabel="Retry"
          onAction={() => void fetchRecords()}
        />
      )}

      {records && records.length === 0 && !isLoading && !error && (
        <div className="flex min-h-[180px] items-center justify-center rounded-lg border border-border-subtle bg-surface px-6 py-10">
          <div className="text-center">
            <div className="mx-auto mb-4 flex h-10 w-10 items-center justify-center rounded border border-green-200 bg-green-100">
              <ShieldCheck className="h-5 w-5 text-green-800" strokeWidth={1.6} />
            </div>
            <h2 className="font-display text-[22px] font-semibold text-ink-primary">
              No tickets in quarantine
            </h2>
          </div>
        </div>
      )}

      {records && records.length > 0 && (
        <div className="space-y-3">
          {error && (
            <div className="rounded border border-warning-amber/30 bg-warning-amber/10 px-4 py-2 text-[13px] text-warning-amber">
              Quarantine records unavailable. Showing the last successful snapshot.
            </div>
          )}
          {records.map((record) => (
            <QuarantineCard
              key={record.quarantine_id}
              record={record}
              isExpanded={expandedId === record.quarantine_id}
              showFullPayload={payloadExpandedId === record.quarantine_id}
              onToggleExpanded={() =>
                setExpandedId((current) =>
                  current === record.quarantine_id ? null : record.quarantine_id
                )
              }
              onTogglePayload={() =>
                setPayloadExpandedId((current) =>
                  current === record.quarantine_id ? null : record.quarantine_id
                )
              }
              onRelease={(verdict) => {
                setPendingRelease({ id: record.quarantine_id, verdict });
                setNote("");
                setReleaseError(null);
              }}
            />
          ))}
        </div>
      )}

      {pendingRelease && selectedRecord && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4">
          <div className="w-full max-w-[520px] rounded-lg border border-border-subtle bg-surface p-4 shadow-xl">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="font-technical text-[10px] font-semibold uppercase tracking-[0.16em] text-ink-tertiary">
                  Confirm Release
                </div>
                <h3 className="mt-1 text-[18px] font-semibold text-ink-primary">
                  {pendingRelease.verdict === "false_positive"
                    ? "False positive"
                    : "Fraud confirmed"}
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setPendingRelease(null)}
                className="flex h-8 w-8 items-center justify-center rounded border border-border-subtle text-ink-secondary transition-colors hover:border-border-defined hover:text-ink-primary"
                aria-label="Close confirmation"
              >
                <XCircle className="h-4 w-4" strokeWidth={1.6} />
              </button>
            </div>
            <div className="mt-3 rounded border border-border-subtle bg-surface-raised p-3 text-[13px] text-ink-secondary">
              <span className="font-medium text-ink-primary">
                {selectedRecord.channel}
              </span>{" "}
              cluster size {selectedRecord.cluster_size}
            </div>
            <label className="mt-3 flex flex-col gap-1">
              <span className="font-technical text-[10px] font-semibold uppercase tracking-[0.16em] text-ink-tertiary">
                Note
              </span>
              <textarea
                value={note}
                onChange={(event) => setNote(event.target.value)}
                className="min-h-[96px] rounded border border-border-subtle bg-surface-raised px-3 py-2 text-[13px] text-ink-primary outline-none transition-colors focus:border-border-defined"
                placeholder="Optional operator note..."
              />
            </label>
            {releaseError && (
              <div className="mt-3 rounded border border-red-alert/30 bg-red-alert/10 px-3 py-2 text-[13px] text-red-alert">
                {releaseError}
              </div>
            )}
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setPendingRelease(null)}
                className="h-10 rounded border border-border-subtle px-3 text-[13px] font-medium text-ink-secondary transition-colors hover:border-border-defined hover:text-ink-primary"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void submitRelease()}
                disabled={isReleasing}
                className={cn(
                  "h-10 rounded px-3 text-[13px] font-semibold text-white transition-colors disabled:opacity-60",
                  pendingRelease.verdict === "false_positive"
                    ? "bg-green-700 hover:bg-green-800"
                    : "bg-red-700 hover:bg-red-800"
                )}
              >
                {isReleasing ? "Releasing..." : "Confirm"}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function QuarantineCard({
  record,
  isExpanded,
  showFullPayload,
  onToggleExpanded,
  onTogglePayload,
  onRelease,
}: {
  record: SemanticQuarantineItem;
  isExpanded: boolean;
  showFullPayload: boolean;
  onToggleExpanded: () => void;
  onTogglePayload: () => void;
  onRelease: (verdict: ReleaseVerdict) => void;
}) {
  const payloadText = payloadPreview(record.ticket_payload_json);
  const shortPayload =
    payloadText.length > 300 ? `${payloadText.slice(0, 300)}...` : payloadText;

  return (
    <article className="rounded-lg border border-border-subtle bg-surface">
      <button
        type="button"
        onClick={onToggleExpanded}
        className="grid w-full grid-cols-[1fr_auto] items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-surface-raised sm:grid-cols-[minmax(160px,1fr)_140px_130px_170px_auto]"
      >
        <div className="min-w-0">
          <span className="inline-flex rounded bg-surface-raised px-2 py-1 font-technical text-[10px] font-semibold uppercase tracking-[0.12em] text-ink-secondary">
            {record.channel}
          </span>
          <div className="mt-2 truncate text-[14px] font-semibold text-ink-primary">
            {record.external_id ?? record.quarantine_id}
          </div>
        </div>
        <div className="hidden text-[13px] text-ink-secondary sm:block">
          {formatRelativeTime(record.created_at)}
        </div>
        <div className="hidden text-[13px] text-ink-secondary sm:block">
          Cluster {record.cluster_size}
        </div>
        <div className="hidden text-[13px] text-ink-secondary sm:block">
          Similarity {similarityScore(record)}
        </div>
        <div className="flex h-8 w-8 items-center justify-center rounded border border-border-subtle text-ink-secondary">
          {isExpanded ? (
            <ChevronUp className="h-4 w-4" strokeWidth={1.6} />
          ) : (
            <ChevronDown className="h-4 w-4" strokeWidth={1.6} />
          )}
        </div>
      </button>

      {isExpanded && (
        <div className="border-t border-border-subtle px-4 py-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <Metric label="Created" value={formatRelativeTime(record.created_at)} />
            <Metric label="Cluster Size" value={String(record.cluster_size)} />
            <Metric label="Similarity" value={similarityScore(record)} />
          </div>

          <div className="mt-4 rounded border border-border-subtle bg-surface-raised p-3">
            <div className="mb-2 font-technical text-[10px] font-semibold uppercase tracking-[0.16em] text-ink-tertiary">
              Ticket Content
            </div>
            <pre className="max-h-[260px] overflow-auto whitespace-pre-wrap break-words text-[12px] leading-relaxed text-ink-secondary">
              {showFullPayload ? payloadText : shortPayload}
            </pre>
            {payloadText.length > 300 && (
              <button
                type="button"
                onClick={onTogglePayload}
                className="mt-3 rounded border border-border-subtle px-2.5 py-1.5 text-[12px] font-medium text-ink-secondary transition-colors hover:border-border-defined hover:text-ink-primary"
              >
                {showFullPayload ? "Hide full payload" : "View full payload"}
              </button>
            )}
          </div>

          <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:justify-end">
            <button
              type="button"
              onClick={() => onRelease("false_positive")}
              className="min-h-10 rounded border border-green-700 px-3 text-[12px] font-semibold text-green-700 transition-colors hover:bg-green-700 hover:text-white"
            >
              FALSE POSITIVE
            </button>
            <button
              type="button"
              onClick={() => onRelease("fraud_confirmed")}
              className="min-h-10 rounded border border-red-700 px-3 text-[12px] font-semibold text-red-700 transition-colors hover:bg-red-700 hover:text-white"
            >
              FRAUD CONFIRMED
            </button>
          </div>
        </div>
      )}
    </article>
  );
}

function FraudEventLog() {
  const [events, setEvents] = useState<SemanticCircuitEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const hasLoadedRef = useRef(false);

  const fetchEvents = useCallback(async () => {
    if (hasLoadedRef.current) {
      setIsRefreshing(true);
    } else {
      setIsLoading(true);
    }
    setError(null);
    try {
      const response = await listSemanticCircuitEvents({ limit: 50 });
      hasLoadedRef.current = true;
      setEvents(response);
    } catch (caught: unknown) {
      setError(formatApiError(caught));
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void fetchEvents();
    const interval = window.setInterval(() => void fetchEvents(), 60_000);
    return () => window.clearInterval(interval);
  }, [fetchEvents]);

  return (
    <section>
      <SectionHeader
        eyebrow="EVENT LOG"
        title="Recent Circuit Events"
        isRefreshing={isRefreshing}
        onRefresh={() => void fetchEvents()}
      />

      {isLoading && !events && <LoadingState label="Loading circuit events..." />}

      {error && !events && !isLoading && (
        <ErrorState
          title="Circuit events unavailable"
          message={error}
          actionLabel="Retry"
          onAction={() => void fetchEvents()}
        />
      )}

      {events && (
        <div className="overflow-hidden rounded-lg border border-border-subtle bg-surface">
          {error && (
            <div className="border-b border-warning-amber/30 bg-warning-amber/10 px-4 py-2 text-[13px] text-warning-amber">
              Circuit events unavailable. Showing the last successful page.
            </div>
          )}
          <div className="overflow-x-auto">
            <div className="min-w-[680px]">
              <div className="grid h-10 grid-cols-[190px_minmax(180px,1fr)_140px_130px] items-center border-b border-border-subtle bg-surface-raised px-3">
                <TableHeader>When</TableHeader>
                <TableHeader>Channel</TableHeader>
                <TableHeader>State</TableHeader>
                <TableHeader>Cluster Size</TableHeader>
              </div>
              {events.length === 0 ? (
                <div className="px-3 py-5 text-[13px] text-ink-secondary">
                  No semantic circuit events recorded.
                </div>
              ) : (
                events.map((event, index) => (
                  <div
                    key={event.event_id}
                    className={cn(
                      "grid min-h-12 grid-cols-[190px_minmax(180px,1fr)_140px_130px] items-center px-3 text-[13px]",
                      index % 2 === 1 && "bg-surface-raised/45"
                    )}
                  >
                    <div className="text-ink-secondary">
                      {formatRelativeTime(event.occurred_at)}
                    </div>
                    <div className="truncate font-medium text-ink-primary">
                      {event.channel}
                    </div>
                    <div>
                      <StateBadge state={event.state} />
                    </div>
                    <div className="text-ink-secondary">
                      {event.cluster_size ?? "-"}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function SectionHeader({
  eyebrow,
  title,
  isRefreshing,
  onRefresh,
}: {
  eyebrow: string;
  title: string;
  isRefreshing: boolean;
  onRefresh: () => void;
}) {
  return (
    <div className="mb-3 flex items-center justify-between gap-3">
      <div>
        <div className="font-technical text-[10px] font-semibold uppercase tracking-[0.16em] text-ink-tertiary">
          {eyebrow}
        </div>
        <h2 className="mt-1 text-[20px] font-semibold text-ink-primary">
          {title}
        </h2>
      </div>
      <button
        type="button"
        onClick={onRefresh}
        className="flex h-10 w-10 items-center justify-center rounded border border-border-subtle bg-surface transition-colors hover:border-border-defined"
        aria-label={`Refresh ${title}`}
      >
        <RefreshCw
          className={cn("h-4 w-4 text-ink-secondary", isRefreshing && "animate-spin")}
          strokeWidth={1.6}
        />
      </button>
    </div>
  );
}

function TableHeader({ children }: { children: React.ReactNode }) {
  return (
    <div className="font-technical text-[10px] font-semibold uppercase tracking-[0.16em] text-ink-tertiary">
      {children}
    </div>
  );
}

function StateBadge({ state }: { state: SemanticCircuitState["state"] }) {
  return (
    <span
      className={cn(
        "inline-flex rounded px-2 py-1 font-technical text-[10px] font-semibold uppercase tracking-[0.12em]",
        STATE_BADGES[state]
      )}
    >
      {state}
    </span>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-border-subtle bg-surface-raised p-3">
      <div className="font-technical text-[10px] font-semibold uppercase tracking-[0.16em] text-ink-tertiary">
        {label}
      </div>
      <div className="mt-1 text-[14px] font-semibold text-ink-primary">
        {value}
      </div>
    </div>
  );
}

function formatRelativeTime(value: string) {
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return value;
  const diffSeconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
  if (diffSeconds < 60) return `${diffSeconds}s ago`;
  const diffMinutes = Math.floor(diffSeconds / 60);
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d ago`;
}

function formatWindow(seconds: number | null) {
  if (seconds === null) return "-";
  if (seconds < 60) return `${seconds}s`;
  const minutes = seconds / 60;
  return Number.isInteger(minutes) ? `${minutes}m` : `${seconds}s`;
}

function payloadPreview(payload: Record<string, unknown>) {
  const content = payload.content;
  if (typeof content === "string" && content) return content;
  const body = payload.body;
  if (typeof body === "string" && body) return body;
  const message = payload.message;
  if (typeof message === "string" && message) return message;
  return JSON.stringify(payload, null, 2);
}

function similarityScore(record: SemanticQuarantineItem) {
  const score = record.metadata.similarity_score;
  if (typeof score === "number") return score.toFixed(2);
  return `>= ${record.similarity_threshold.toFixed(2)}`;
}
