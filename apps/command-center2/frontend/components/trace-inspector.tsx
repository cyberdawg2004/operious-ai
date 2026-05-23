"use client";

import { useCallback, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Copy,
  Cpu,
  ExternalLink,
  Search,
  Shield,
  XCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  type ApiPage,
  getApiBaseUrl,
  listTraceSpans,
  type OperationalTraceSpan,
} from "@/lib/api";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-state";
import { useApiResource } from "@/lib/use-api-resource";

const substrateColors: Record<string, string> = {
  BOUNDARY: "#1A4A9A",
  GOVERNANCE: "#A8882C",
  COORDINATION: "#4A5468",
  SESSION: "#2E7D5C",
  EXECUTION: "#0D2860",
  SUPERVISOR: "#6B5418",
  ARBITRATION: "#A6342D",
  HARDENING: "#8A93A4",
};

type TraceInspectorProps = {
  initialTraceId?: string | null;
};

export function TraceInspector({ initialTraceId }: TraceInspectorProps) {
  const [searchValue, setSearchValue] = useState(initialTraceId ?? "");
  const [loadedTraceId, setLoadedTraceId] = useState<string | null>(
    initialTraceId?.trim() || null
  );
  const [selectedSpan, setSelectedSpan] = useState<OperationalTraceSpan | null>(null);
  const [showRawJson, setShowRawJson] = useState(false);
  const [copyStatus, setCopyStatus] = useState<string | null>(null);

  const loadTraceSpans = useCallback(async (): Promise<ApiPage<OperationalTraceSpan>> => {
    if (!loadedTraceId) {
      return { items: [], total: 0, offset: 0 };
    }
    return listTraceSpans({
      trace_id: loadedTraceId,
      limit: 100,
      offset: 0,
    });
  }, [loadedTraceId]);

  const { data, error, isLoading, reload } = useApiResource(loadTraceSpans);
  const spans = useMemo(() => data?.items ?? [], [data?.items]);
  const total = data?.total ?? 0;
  const currentSpan =
    selectedSpan && spans.some((span) => span.span_id === selectedSpan.span_id)
      ? selectedSpan
      : spans[0] ?? null;
  const selectedMetric = currentSpan
    ? extractAttribute(currentSpan, ["confidence", "score"])
    : null;
  const metadata = useMemo(() => deriveTraceMetadata(spans), [spans]);

  const handleOpenTrace = () => {
    const normalized = searchValue.trim();
    setLoadedTraceId(normalized || null);
    setSelectedSpan(null);
    setCopyStatus(null);
    setShowRawJson(false);
  };

  const handleCopySpan = async () => {
    if (!currentSpan) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(currentSpan, null, 2));
      setCopyStatus("Event data copied");
    } catch {
      setCopyStatus("Clipboard access denied");
    }
  };

  const handleOpenRawEndpoint = () => {
    if (!loadedTraceId) return;
    const url = new URL(`${getApiBaseUrl()}/observability/traces`);
    url.searchParams.set("trace_id", loadedTraceId);
    url.searchParams.set("limit", "100");
    url.searchParams.set("offset", "0");
    window.open(url.toString(), "_blank", "noopener,noreferrer");
  };

  return (
    <div
      className="flex-1 min-h-screen py-8 px-12"
      style={{ backgroundColor: "var(--canvas)" }}
    >
      <div className="mb-8">
        <div
          className="font-mono text-[11px] uppercase tracking-[0.18em] mb-2"
          style={{ color: "var(--gold-primary)" }}
        >
          TRACE · INSPECTOR
        </div>

        <div className="flex items-center justify-between">
          <h1
            className="font-display text-[32px] font-bold"
            style={{ color: "var(--ink-primary)" }}
          >
            Trace Inspector
          </h1>

          <div className="flex items-center gap-3">
            <div className="relative">
              <Search
                className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5"
                style={{ color: "var(--ink-tertiary)" }}
              />
              <input
                type="text"
                placeholder="Trace ID or Session ID..."
                value={searchValue}
                onChange={(e) => setSearchValue(e.target.value)}
                className="w-[320px] h-9 pl-9 pr-4 rounded font-sans text-[13px] outline-none transition-all duration-160"
                style={{
                  backgroundColor: "var(--surface-raised)",
                  border: "1px solid var(--border-subtle)",
                  color: "var(--ink-primary)",
                }}
                onFocus={(e) =>
                  (e.target.style.borderColor = "var(--gold-primary)")
                }
                onBlur={(e) =>
                  (e.target.style.borderColor = "var(--border-subtle)")
                }
                onKeyDown={(e) => e.key === "Enter" && handleOpenTrace()}
              />
            </div>
            <button
              onClick={handleOpenTrace}
              className="h-9 px-4 rounded font-sans text-[13px] font-medium text-white transition-opacity duration-160 hover:opacity-90"
              style={{ backgroundColor: "var(--ink-primary)" }}
            >
              Open Trace
            </button>
          </div>
        </div>
      </div>

      {!loadedTraceId && !isLoading && (
        <EmptyState
          title="No trace selected"
          message="Enter a trace ID or session ID to request recorded spans from the observability endpoint."
        />
      )}

      {isLoading && <LoadingState label="Loading trace spans..." />}

      {error && !isLoading && (
        <ErrorState
          title="Trace data unavailable"
          message={error}
          actionLabel="Retry"
          onAction={reload}
        />
      )}

      {loadedTraceId && !isLoading && !error && spans.length === 0 && (
        <EmptyState
          title="No spans recorded"
          message="The backend returned an empty trace span page for this identifier."
          actionLabel="Refresh trace"
          onAction={reload}
        />
      )}

      {loadedTraceId && spans.length > 0 && !isLoading && !error && (
        <>
          <div
            className="flex items-stretch rounded-lg p-4 mb-6"
            style={{
              backgroundColor: "var(--surface-raised)",
              border: "1px solid var(--border-subtle)",
            }}
          >
            <MetadataField label="TRACE ID" value={loadedTraceId} mono />
            <Divider />
            <MetadataField label="TENANT" value={metadata.tenantId} />
            <Divider />
            <MetadataField label="FIRST SPAN" value={metadata.firstSpan} mono />
            <Divider />
            <MetadataField label="STATUS" value={<TraceStatusBadge hasErrors={metadata.hasErrors} />} />
            <Divider />
            <MetadataField label="TOTAL SPANS" value={String(total)} mono />
            <Divider />
            <MetadataField label="DURATION" value={metadata.duration} mono />
            <Divider />
            <MetadataField label="POLICY CHAIN" value={metadata.policyChain} mono />
          </div>

          <div className="flex gap-6">
            <div
              className="w-[60%] rounded-lg p-6"
              style={{
                backgroundColor: "var(--surface-raised)",
                border: "1px solid var(--border-subtle)",
                minHeight: "600px",
              }}
            >
              <div
                className="font-mono text-[11px] uppercase tracking-[0.18em] mb-4"
                style={{ color: "var(--ink-tertiary)" }}
              >
                OPERATIONAL TIMELINE
              </div>

              <div
                className="flex flex-wrap gap-4 mb-6 pb-4"
                style={{ borderBottom: "1px solid var(--border-subtle)" }}
              >
                {Object.entries(substrateColors).map(([name, color]) => (
                  <div key={name} className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: color }} />
                    <span
                      className="font-mono text-[11px] uppercase"
                      style={{ color: "var(--ink-secondary)" }}
                    >
                      {name}
                    </span>
                  </div>
                ))}
              </div>

              <div className="relative">
                <div
                  className="absolute left-[60px] top-0 bottom-0 w-px"
                  style={{ backgroundColor: "var(--border-subtle)" }}
                />

                <div className="space-y-1">
                  {spans.map((span) => (
                    <button
                      key={span.span_id}
                      onClick={() => {
                        setSelectedSpan(span);
                        setShowRawJson(false);
                        setCopyStatus(null);
                      }}
                      className={cn(
                        "w-full flex items-center gap-4 px-3 py-2.5 rounded-lg text-left transition-all duration-160",
                        currentSpan?.span_id === span.span_id
                          ? "ring-2"
                          : "hover:bg-[var(--surface-sunken)]"
                      )}
                      style={{
                        backgroundColor:
                          currentSpan?.span_id === span.span_id
                            ? "rgba(183, 135, 38, 0.08)"
                            : "transparent",
                        ["--tw-ring-color" as string]: "var(--gold-primary)",
                      }}
                    >
                      <span
                        className="font-mono text-[11px] w-[52px] shrink-0 tabular-nums"
                        style={{ color: "var(--ink-tertiary)" }}
                      >
                        {formatClock(span.started_at)}
                      </span>

                      <div className="relative z-10">
                        <span
                          className="block w-3 h-3 rounded-full ring-2 ring-[var(--surface-raised)]"
                          style={{ backgroundColor: colorForSubstrate(span.substrate) }}
                        />
                      </div>

                      <div className="flex-1 min-w-0">
                        <span className="font-mono text-[12px] uppercase tracking-wide">
                          <span style={{ color: colorForSubstrate(span.substrate) }}>
                            {span.substrate}
                          </span>
                          <span style={{ color: "var(--ink-primary)" }}>
                            .{span.operation || span.span_name}
                          </span>
                        </span>
                      </div>

                      <div className="flex items-center gap-3 shrink-0">
                        <span
                          className="font-mono text-[11px] tabular-nums"
                          style={{ color: "var(--ink-tertiary)" }}
                        >
                          {formatLatency(span.latency_ms)}
                        </span>
                        <StatusIcon status={span.status} />
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div
              className="w-[40%] rounded-lg"
              style={{
                backgroundColor: "var(--surface-raised)",
                border: "1px solid var(--border-subtle)",
                minHeight: "600px",
              }}
            >
              <div
                className="px-6 py-4 flex items-center justify-between"
                style={{ borderBottom: "1px solid var(--border-subtle)" }}
              >
                <span
                  className="font-mono text-[11px] uppercase tracking-[0.18em]"
                  style={{ color: "var(--ink-tertiary)" }}
                >
                  EVENT INSPECTOR
                </span>
                {currentSpan && (
                  <div className="flex items-center gap-2">
                    <button
                      onClick={handleCopySpan}
                      className="p-1.5 rounded transition-colors duration-160 hover:bg-[var(--surface-sunken)]"
                      title="Copy event data"
                    >
                      <Copy className="w-4 h-4" style={{ color: "var(--ink-tertiary)" }} />
                    </button>
                    <button
                      onClick={handleOpenRawEndpoint}
                      className="p-1.5 rounded transition-colors duration-160 hover:bg-[var(--surface-sunken)]"
                      title="Open trace endpoint"
                    >
                      <ExternalLink className="w-4 h-4" style={{ color: "var(--ink-tertiary)" }} />
                    </button>
                  </div>
                )}
              </div>

              {currentSpan ? (
                <div className="p-6 space-y-6">
                  <div>
                    <div className="flex items-center gap-2 mb-2">
                      <StatusIcon status={currentSpan.status} />
                      {copyStatus && (
                        <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-tertiary">
                          {copyStatus}
                        </span>
                      )}
                    </div>
                    <h3 className="font-mono text-[14px] uppercase tracking-wide mb-1">
                      <span style={{ color: colorForSubstrate(currentSpan.substrate) }}>
                        {currentSpan.substrate}
                      </span>
                      <span style={{ color: "var(--ink-primary)" }}>
                        .{currentSpan.operation || currentSpan.span_name}
                      </span>
                    </h3>
                    <p
                      className="font-mono text-[12px]"
                      style={{ color: "var(--ink-tertiary)" }}
                    >
                      {currentSpan.span_id} · {formatClock(currentSpan.started_at)}
                    </p>
                  </div>

                  <div
                    className="flex flex-wrap gap-4 p-4 rounded-lg"
                    style={{ backgroundColor: "var(--surface-sunken)" }}
                  >
                    <Metric icon={<Clock className="w-4 h-4" />} value={formatLatency(currentSpan.latency_ms)} />
                    <Metric icon={<Cpu className="w-4 h-4" />} value={currentSpan.span_name} />
                    {selectedMetric !== null && selectedMetric !== undefined && (
                      <Metric
                        icon={<Shield className="w-4 h-4" />}
                        value={String(selectedMetric)}
                      />
                    )}
                  </div>

                  <div className="space-y-4">
                    <DetailRow label="SPAN NAME" value={currentSpan.span_name} />
                    <DetailRow label="STATUS" value={currentSpan.status} />
                    {currentSpan.error && <DetailRow label="ERROR" value={currentSpan.error} />}
                    {Object.entries(currentSpan.attributes).map(([key, value]) => (
                      <DetailRow key={key} label={key} value={stringifyValue(value)} />
                    ))}
                  </div>

                  <div>
                    <button
                      onClick={() => setShowRawJson((open) => !open)}
                      className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.18em] transition-colors duration-160"
                      style={{ color: "var(--ink-tertiary)" }}
                    >
                      {showRawJson ? (
                        <ChevronDown className="w-3 h-3" />
                      ) : (
                        <ChevronRight className="w-3 h-3" />
                      )}
                      View Raw JSON
                    </button>
                    {showRawJson && (
                      <pre className="mt-3 max-h-[260px] overflow-auto rounded border border-border-subtle bg-surface-sunken p-3 text-[11px] leading-relaxed text-ink-secondary">
                        {JSON.stringify(currentSpan, null, 2)}
                      </pre>
                    )}
                  </div>
                </div>
              ) : (
                <div className="flex items-center justify-center h-[500px]">
                  <p
                    className="font-sans text-[14px] italic"
                    style={{ color: "var(--ink-tertiary)" }}
                  >
                    Select an event to inspect
                  </p>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function TraceStatusBadge({ hasErrors }: { hasErrors: boolean }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium uppercase"
      style={{
        backgroundColor: hasErrors ? "rgba(220, 38, 38, 0.1)" : "rgba(22, 163, 74, 0.1)",
        color: hasErrors ? "var(--red-alert)" : "var(--green-success)",
      }}
    >
      {hasErrors ? "ERRORS RECORDED" : "RECORDED"}
    </span>
  );
}

function StatusIcon({ status }: { status: string }) {
  const normalized = status.toLowerCase();
  if (normalized.includes("error") || normalized.includes("fail")) {
    return <XCircle className="w-4 h-4 text-red-alert" />;
  }
  if (normalized.includes("warn") || normalized.includes("degraded")) {
    return <AlertTriangle className="w-4 h-4 text-warning-amber" />;
  }
  return <CheckCircle2 className="w-4 h-4 text-green-success" />;
}

function MetadataField({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="flex-1 px-4 first:pl-0 last:pr-0">
      <div
        className="font-mono text-[10px] uppercase tracking-[0.18em] mb-1"
        style={{ color: "var(--ink-tertiary)" }}
      >
        {label}
      </div>
      {typeof value === "string" ? (
        <div
          className={cn(
            "text-[13px] font-medium",
            mono ? "font-mono" : "font-sans"
          )}
          style={{ color: "var(--ink-primary)" }}
        >
          {value}
        </div>
      ) : (
        value
      )}
    </div>
  );
}

function Divider() {
  return (
    <div
      className="w-px self-stretch mx-2"
      style={{ backgroundColor: "var(--border-subtle)" }}
    />
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div
        className="font-mono text-[10px] uppercase tracking-[0.18em] mb-1"
        style={{ color: "var(--ink-tertiary)" }}
      >
        {label}
      </div>
      <div
        className="font-mono text-[13px] break-words"
        style={{ color: "var(--ink-primary)" }}
      >
        {value}
      </div>
    </div>
  );
}

function Metric({ icon, value }: { icon: React.ReactNode; value: string }) {
  return (
    <div className="flex items-center gap-2 min-w-0">
      <span className="text-ink-tertiary">{icon}</span>
      <span className="font-mono text-[13px] text-ink-primary truncate">
        {value}
      </span>
    </div>
  );
}

function deriveTraceMetadata(spans: OperationalTraceSpan[]) {
  if (spans.length === 0) {
    return {
      tenantId: "No tenant",
      firstSpan: "No spans",
      duration: "No spans",
      policyChain: "Not recorded",
      hasErrors: false,
    };
  }
  const sorted = [...spans].sort(
    (a, b) => new Date(a.started_at).getTime() - new Date(b.started_at).getTime()
  );
  const first = sorted[0];
  const startedAt = new Date(first.started_at).getTime();
  const endedAt = Math.max(...sorted.map((span) => new Date(span.ended_at).getTime()));
  const policyChain = sorted
    .map((span) => extractAttribute(span, ["governance_chain_id", "policy_chain", "policy_id", "policyId"]))
    .find((value): value is string => typeof value === "string" && value.length > 0);
  return {
    tenantId: first.tenant_id,
    firstSpan: first.span_name,
    duration:
      Number.isNaN(startedAt) || Number.isNaN(endedAt)
        ? "Unknown"
        : formatLatency(Math.max(0, endedAt - startedAt)),
    policyChain: policyChain ?? "Not recorded",
    hasErrors: sorted.some((span) => {
      const status = span.status.toLowerCase();
      return status.includes("error") || status.includes("fail");
    }),
  };
}

function extractAttribute(span: OperationalTraceSpan, keys: string[]): unknown {
  for (const key of keys) {
    if (key in span.attributes) return span.attributes[key];
  }
  return null;
}

function colorForSubstrate(substrate: string): string {
  return substrateColors[substrate.toUpperCase()] ?? "#8A93A4";
}

function formatClock(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Invalid";
  return new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

function formatLatency(milliseconds: number): string {
  if (milliseconds < 1000) return `${Math.round(milliseconds)}ms`;
  const totalSeconds = Math.round(milliseconds / 1000);
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}m ${seconds}s`;
}

function stringifyValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (value === null || value === undefined) return "null";
  return JSON.stringify(value);
}
