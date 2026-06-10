"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  Activity,
  ArrowUpRight,
  CheckCircle2,
  Clock,
  Gauge,
  Inbox,
  LifeBuoy,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { ErrorState } from "@/components/data-state";
import { dashboardRoutes } from "@/lib/dashboard-routes";
import {
  getQueueStatus,
  listActionApprovals,
  listActiveCrisisDeployments,
  listCaseApprovals,
  listEscalations,
  listSemanticCircuitStates,
  readOperationalMetrics,
  type CrisisDeployment,
  type OperationalMetrics,
  type QueueStatusResponse,
  type SemanticCircuitState,
} from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Command Overview — the executive landing for the Command Center.
 *
 * Answers, at a glance: "What is my AI workforce doing right now?"
 * Every number here is sourced from existing read-only operational endpoints;
 * this view introduces no new backend behaviour. It is the first consumer of
 * the operational-metrics endpoint, reframing technical telemetry into the
 * operational language an operations leader expects.
 */

const REFRESH_INTERVAL_MS = 30_000;

/**
 * Conservative baseline used only for the clearly-labelled "estimated time
 * saved" tile. Exposed in the UI so the assumption is never hidden.
 */
const MINUTES_SAVED_PER_AUTOMATED_RESOLUTION = 8;

type WindowOption = { id: string; label: string; hours: number };

const WINDOW_OPTIONS: WindowOption[] = [
  { id: "24h", label: "Last 24 hours", hours: 24 },
  { id: "7d", label: "Last 7 days", hours: 24 * 7 },
];

type OverviewData = {
  metrics: OperationalMetrics | null;
  queue: QueueStatusResponse | null;
  circuits: SemanticCircuitState[];
  crisis: CrisisDeployment[];
  pendingActionApprovals: number | null;
  pendingCaseApprovals: number | null;
  pendingEscalations: number | null;
};

const EMPTY_DATA: OverviewData = {
  metrics: null,
  queue: null,
  circuits: [],
  crisis: [],
  pendingActionApprovals: null,
  pendingCaseApprovals: null,
  pendingEscalations: null,
};

export function CommandOverview() {
  const [windowId, setWindowId] = useState<string>(WINDOW_OPTIONS[0].id);
  const [data, setData] = useState<OverviewData>(EMPTY_DATA);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const hasLoadedRef = useRef(false);

  const windowOption =
    WINDOW_OPTIONS.find((option) => option.id === windowId) ?? WINDOW_OPTIONS[0];

  const load = useCallback(async () => {
    if (hasLoadedRef.current) {
      setIsRefreshing(true);
    } else {
      setIsLoading(true);
    }

    const windowEnd = new Date();
    const windowStart = new Date(
      windowEnd.getTime() - windowOption.hours * 60 * 60 * 1000
    );

    const [
      metrics,
      queue,
      circuits,
      crisis,
      actionApprovals,
      caseAwaiting,
      caseSmeReview,
      escalations,
    ] = await Promise.allSettled([
      readOperationalMetrics(windowStart, windowEnd),
      getQueueStatus(),
      listSemanticCircuitStates(),
      listActiveCrisisDeployments(),
      listActionApprovals({ status: "pending", limit: 100, offset: 0 }),
      listCaseApprovals({ status: "awaiting_approval", limit: 1, offset: 0 }),
      listCaseApprovals({ status: "pending_sme_review", limit: 1, offset: 0 }),
      listEscalations({ status: "pending", limit: 1, offset: 0 }),
    ]);

    const pendingCaseApprovals =
      caseAwaiting.status === "fulfilled" || caseSmeReview.status === "fulfilled"
        ? (caseAwaiting.status === "fulfilled" ? caseAwaiting.value.total : 0) +
          (caseSmeReview.status === "fulfilled" ? caseSmeReview.value.total : 0)
        : null;

    setData({
      metrics: metrics.status === "fulfilled" ? metrics.value : null,
      queue: queue.status === "fulfilled" ? queue.value : null,
      circuits: circuits.status === "fulfilled" ? circuits.value : [],
      crisis: crisis.status === "fulfilled" ? crisis.value : [],
      pendingActionApprovals:
        actionApprovals.status === "fulfilled"
          ? actionApprovals.value.length
          : null,
      pendingCaseApprovals,
      pendingEscalations:
        escalations.status === "fulfilled" ? escalations.value.total : null,
    });

    // Surface an error only when nothing at all could be loaded.
    if (metrics.status === "rejected" && queue.status === "rejected") {
      setError(
        metrics.reason instanceof Error
          ? metrics.reason.message
          : "Operational data is currently unavailable."
      );
    } else {
      setError(null);
    }

    hasLoadedRef.current = true;
    setLastUpdated(new Date());
    setIsLoading(false);
    setIsRefreshing(false);
  }, [windowOption.hours]);

  useEffect(() => {
    const timeout = window.setTimeout(() => void load(), 0);
    const interval = window.setInterval(() => void load(), REFRESH_INTERVAL_MS);
    return () => {
      window.clearTimeout(timeout);
      window.clearInterval(interval);
    };
  }, [load]);

  const derived = useMemo(() => deriveSummary(data), [data]);

  return (
    <main className="min-w-0 flex-1 overflow-auto bg-canvas p-4 sm:p-6 lg:p-8">
      <div className="mb-2 font-mono text-[11px] uppercase tracking-[0.18em] text-ink-tertiary">
        COMMAND CENTER · OVERVIEW
      </div>
      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="font-display text-[32px] font-semibold leading-tight text-ink-primary">
            Command Overview
          </h1>
          <p className="mt-1 max-w-2xl text-[13px] text-ink-secondary">
            What your AI workforce is doing across the {windowOption.label.toLowerCase()}.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <WindowToggle value={windowId} onChange={setWindowId} />
          <button
            type="button"
            onClick={() => void load()}
            className="flex h-10 w-10 items-center justify-center rounded-md border border-border-subtle bg-surface transition-all duration-150 hover:border-border-defined"
            aria-label="Refresh overview"
          >
            <RefreshCw
              size={14}
              strokeWidth={1.6}
              className={cn("text-ink-secondary", isRefreshing && "animate-spin")}
            />
          </button>
        </div>
      </div>

      {error && !data.metrics && !isLoading ? (
        <ErrorState
          title="Overview unavailable"
          message={error}
          actionLabel="Retry"
          onAction={() => void load()}
        />
      ) : (
        <div className="animate-cc-fade-in space-y-6">
          {derived.risks.length > 0 && <RiskBanner risks={derived.risks} />}

          {/* Headline workforce KPIs */}
          <section className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <KpiCard
              icon={Activity}
              label="Operations handled"
              value={formatCount(data.metrics?.ticket_throughput)}
              hint="Customer issues processed"
              loading={isLoading}
            />
            <KpiCard
              icon={Sparkles}
              label="Automation rate"
              value={formatPercent(derived.automationRate)}
              hint="Resolved without human action"
              tone={toneForRate(derived.automationRate)}
              loading={isLoading}
            />
            <KpiCard
              icon={Inbox}
              label="Human reviews needed"
              value={formatCount(derived.pendingTotal)}
              hint="Decisions waiting on your team"
              tone={derived.pendingTotal && derived.pendingTotal > 0 ? "warn" : "ok"}
              loading={isLoading}
            />
            <KpiCard
              icon={Gauge}
              label="Quality score"
              value={formatScore(data.metrics?.qa_score_average)}
              hint="Average QA review score"
              tone={toneForQa(data.metrics?.qa_score_average)}
              loading={isLoading}
            />
          </section>

          {/* Secondary operational measures */}
          <section className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <KpiCard
              icon={Clock}
              label="Avg resolution time"
              value={formatDuration(data.metrics?.execution_latency_ms_avg)}
              hint="Per automated operation"
              loading={isLoading}
              compact
            />
            <KpiCard
              icon={Clock}
              label="Est. analyst time saved"
              value={derived.timeSavedLabel}
              hint={`Est. · ${MINUTES_SAVED_PER_AUTOMATED_RESOLUTION} min/resolution baseline`}
              loading={isLoading}
              compact
            />
            <KpiCard
              icon={ShieldCheck}
              label="Safety reviews"
              value={formatCount(data.metrics?.governance_decision_count)}
              hint={`${formatCount(data.metrics?.governance_deny_count)} blocked · ${formatPercent(
                data.metrics?.governance_deny_rate ?? null
              )} block rate`}
              loading={isLoading}
              compact
            />
            <KpiCard
              icon={LifeBuoy}
              label="Escalation rate"
              value={formatPercent(data.metrics?.escalation_rate ?? null)}
              hint={`${formatCount(data.metrics?.escalation_count)} cases escalated`}
              tone={toneForEscalation(data.metrics?.escalation_rate)}
              loading={isLoading}
              compact
            />
          </section>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <PendingDecisionsPanel
              actionApprovals={data.pendingActionApprovals}
              caseApprovals={data.pendingCaseApprovals}
              escalations={data.pendingEscalations}
              loading={isLoading}
            />
            <SystemHealthPanel
              health={derived.health}
              queueBreakdown={derived.queueBreakdown}
              trippedCircuits={derived.trippedCircuits}
              activeCrisis={data.crisis.length}
              loading={isLoading}
            />
          </div>

          <p className="text-[11px] text-ink-quaternary">
            {lastUpdated
              ? `Updated ${lastUpdated.toLocaleTimeString()} · refreshes automatically every 30s`
              : "Loading operational telemetry…"}
          </p>
        </div>
      )}
    </main>
  );
}

/* ─────────────────────────  Derivation  ───────────────────────── */

type HealthLevel = "operational" | "degraded" | "critical";

function deriveSummary(data: OverviewData) {
  const metrics = data.metrics;

  const automationRate =
    metrics && metrics.execution_count > 0
      ? metrics.completed_execution_count / metrics.execution_count
      : null;

  const completed = metrics?.completed_execution_count ?? 0;
  const minutesSaved = completed * MINUTES_SAVED_PER_AUTOMATED_RESOLUTION;
  const timeSavedLabel = metrics ? formatMinutesSaved(minutesSaved) : "—";

  const pendingValues = [
    data.pendingActionApprovals,
    data.pendingCaseApprovals,
    data.pendingEscalations,
  ];
  const pendingTotal = pendingValues.some((value) => value !== null)
    ? pendingValues.reduce<number>((sum, value) => sum + (value ?? 0), 0)
    : null;

  const queues = data.queue ? Object.values(data.queue.queues) : [];
  const queueBreakdown = {
    ok: queues.filter((q) => q.status === "ok").length,
    warn: queues.filter((q) => q.status === "warn").length,
    critical: queues.filter((q) => q.status === "critical").length,
    total: queues.length,
  };

  const trippedCircuits = data.circuits.filter((c) => c.state === "TRIPPED").length;
  const activeCrisis = data.crisis.length;

  let health: HealthLevel = "operational";
  if (activeCrisis > 0 || queueBreakdown.critical > 0) {
    health = "critical";
  } else if (trippedCircuits > 0 || queueBreakdown.warn > 0) {
    health = "degraded";
  }

  const risks: RiskItem[] = [];
  if (activeCrisis > 0) {
    risks.push({
      label: `${activeCrisis} active crisis ${activeCrisis === 1 ? "rule" : "rules"} deployed`,
      href: dashboardRoutes.crisis,
    });
  }
  if (trippedCircuits > 0) {
    risks.push({
      label: `${trippedCircuits} fraud ${trippedCircuits === 1 ? "circuit" : "circuits"} tripped`,
      href: dashboardRoutes.fraud,
    });
  }
  if (queueBreakdown.critical > 0) {
    risks.push({
      label: `${queueBreakdown.critical} work ${queueBreakdown.critical === 1 ? "queue" : "queues"} critically backed up`,
      href: dashboardRoutes["queue-status"],
    });
  }

  return {
    automationRate,
    timeSavedLabel,
    pendingTotal,
    queueBreakdown,
    trippedCircuits,
    health,
    risks,
  };
}

/* ─────────────────────────  Panels  ───────────────────────── */

type RiskItem = { label: string; href: string };

function RiskBanner({ risks }: { risks: RiskItem[] }) {
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-red-alert/30 bg-red-alert/10 p-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-2.5">
        <ShieldAlert size={18} strokeWidth={1.7} className="shrink-0 text-red-alert" />
        <div>
          <p className="text-[13px] font-semibold text-ink-primary">
            Attention required
          </p>
          <p className="text-[12px] text-ink-secondary">
            {risks.map((risk) => risk.label).join(" · ")}
          </p>
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        {risks.map((risk) => (
          <Link
            key={risk.href}
            href={risk.href}
            className="inline-flex items-center gap-1 rounded-md border border-red-alert/30 bg-surface px-2.5 py-1.5 text-[12px] font-medium text-red-alert transition-colors hover:bg-red-alert/10"
          >
            Review
            <ArrowUpRight size={12} strokeWidth={2} />
          </Link>
        ))}
      </div>
    </div>
  );
}

type Tone = "ok" | "warn" | "danger" | "neutral";

function KpiCard({
  icon: Icon,
  label,
  value,
  hint,
  tone = "neutral",
  loading,
  compact,
}: {
  icon: React.ElementType;
  label: string;
  value: string;
  hint?: string;
  tone?: Tone;
  loading?: boolean;
  compact?: boolean;
}) {
  const toneColor =
    tone === "ok"
      ? "text-green-success"
      : tone === "warn"
        ? "text-warning-amber"
        : tone === "danger"
          ? "text-red-alert"
          : "text-ink-primary";

  return (
    <div className="cc-card cc-card-hover p-4">
      <div className="flex items-center justify-between">
        <span className="eyebrow">{label}</span>
        <Icon size={15} strokeWidth={1.6} className="text-ink-tertiary" />
      </div>
      <div
        className={cn(
          "mt-3 font-display font-semibold tabular-nums",
          compact ? "text-[24px]" : "text-[30px]",
          loading ? "text-ink-quaternary" : toneColor
        )}
      >
        {loading ? "—" : value}
      </div>
      {hint && <p className="mt-1 text-[11.5px] text-ink-tertiary">{hint}</p>}
    </div>
  );
}

function PendingDecisionsPanel({
  actionApprovals,
  caseApprovals,
  escalations,
  loading,
}: {
  actionApprovals: number | null;
  caseApprovals: number | null;
  escalations: number | null;
  loading?: boolean;
}) {
  const rows = [
    {
      label: "Action approvals",
      hint: "Governed tools awaiting sign-off",
      count: actionApprovals,
      href: dashboardRoutes.approvals,
      icon: Inbox,
    },
    {
      label: "Case approvals",
      hint: "AI resolutions awaiting human review",
      count: caseApprovals,
      href: dashboardRoutes["case-approvals"],
      icon: CheckCircle2,
    },
    {
      label: "Escalations",
      hint: "Cases handed off for human resolution",
      count: escalations,
      href: dashboardRoutes.escalations,
      icon: LifeBuoy,
    },
  ];

  return (
    <section className="cc-card overflow-hidden">
      <PanelHeader title="Pending decisions" subtitle="Work waiting on a human" />
      <div className="divide-y divide-border-subtle">
        {rows.map((row) => {
          const RowIcon = row.icon;
          const hasWork = (row.count ?? 0) > 0;
          return (
            <Link
              key={row.href}
              href={row.href}
              className="flex items-center gap-3 px-4 py-3.5 transition-colors hover:bg-surface-raised"
            >
              <div
                className={cn(
                  "flex h-9 w-9 shrink-0 items-center justify-center rounded-md border",
                  hasWork
                    ? "border-gold-primary/30 bg-gold-bg text-gold-primary"
                    : "border-border-subtle bg-surface-raised text-ink-tertiary"
                )}
              >
                <RowIcon size={16} strokeWidth={1.6} />
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-[13px] font-medium text-ink-primary">{row.label}</p>
                <p className="truncate text-[11.5px] text-ink-tertiary">{row.hint}</p>
              </div>
              <span
                className={cn(
                  "font-display text-[20px] font-semibold tabular-nums",
                  loading
                    ? "text-ink-quaternary"
                    : hasWork
                      ? "text-ink-primary"
                      : "text-ink-tertiary"
                )}
              >
                {loading ? "—" : (row.count ?? "—")}
              </span>
              <ArrowUpRight size={14} strokeWidth={1.8} className="text-ink-quaternary" />
            </Link>
          );
        })}
      </div>
    </section>
  );
}

function SystemHealthPanel({
  health,
  queueBreakdown,
  trippedCircuits,
  activeCrisis,
  loading,
}: {
  health: HealthLevel;
  queueBreakdown: { ok: number; warn: number; critical: number; total: number };
  trippedCircuits: number;
  activeCrisis: number;
  loading?: boolean;
}) {
  const healthConfig: Record<HealthLevel, { label: string; chip: string }> = {
    operational: { label: "All systems operational", chip: "cc-chip-ok" },
    degraded: { label: "Degraded — monitoring", chip: "cc-chip-warn" },
    critical: { label: "Critical — action needed", chip: "cc-chip-danger" },
  };
  const config = healthConfig[health];

  return (
    <section className="cc-card overflow-hidden">
      <PanelHeader title="System health" subtitle="Live platform status" />
      <div className="px-4 pb-4 pt-4">
        <div className="mb-4 flex items-center justify-between rounded-md border border-border-subtle bg-surface-raised px-3 py-2.5">
          <span className="text-[12.5px] font-medium text-ink-primary">
            Overall status
          </span>
          <span className={cn("cc-chip", loading ? "" : config.chip)}>
            {loading ? "Checking…" : config.label}
          </span>
        </div>
        <div className="space-y-2.5">
          <HealthRow
            label="Work queues"
            detail={`${queueBreakdown.ok}/${queueBreakdown.total} healthy`}
            tone={
              queueBreakdown.critical > 0
                ? "danger"
                : queueBreakdown.warn > 0
                  ? "warn"
                  : "ok"
            }
            loading={loading}
          />
          <HealthRow
            label="Fraud circuits"
            detail={trippedCircuits > 0 ? `${trippedCircuits} tripped` : "All closed"}
            tone={trippedCircuits > 0 ? "danger" : "ok"}
            loading={loading}
          />
          <HealthRow
            label="Crisis controls"
            detail={activeCrisis > 0 ? `${activeCrisis} active` : "None active"}
            tone={activeCrisis > 0 ? "danger" : "ok"}
            loading={loading}
          />
        </div>
      </div>
    </section>
  );
}

function HealthRow({
  label,
  detail,
  tone,
  loading,
}: {
  label: string;
  detail: string;
  tone: Tone;
  loading?: boolean;
}) {
  const dot =
    tone === "ok"
      ? "bg-green-success"
      : tone === "warn"
        ? "bg-warning-amber"
        : tone === "danger"
          ? "bg-red-alert"
          : "bg-ink-quaternary";
  return (
    <div className="flex items-center justify-between px-1">
      <span className="text-[12.5px] text-ink-body">{label}</span>
      <span className="flex items-center gap-2 text-[12px] text-ink-secondary">
        {loading ? (
          "—"
        ) : (
          <>
            <span className={cn("h-2 w-2 rounded-full", dot)} />
            {detail}
          </>
        )}
      </span>
    </div>
  );
}

function PanelHeader({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="border-b border-border-subtle px-4 py-3">
      <h2 className="heading-section">{title}</h2>
      <p className="text-[11.5px] text-ink-tertiary">{subtitle}</p>
    </div>
  );
}

function WindowToggle({
  value,
  onChange,
}: {
  value: string;
  onChange: (id: string) => void;
}) {
  return (
    <div className="inline-flex h-10 items-center rounded-md border border-border-subtle bg-surface p-0.5">
      {WINDOW_OPTIONS.map((option) => (
        <button
          key={option.id}
          type="button"
          onClick={() => onChange(option.id)}
          className={cn(
            "flex h-full items-center rounded px-3 text-[12px] font-medium transition-colors",
            value === option.id
              ? "bg-gold-bg text-ink-primary"
              : "text-ink-tertiary hover:text-ink-secondary"
          )}
        >
          {option.id.toUpperCase()}
        </button>
      ))}
    </div>
  );
}

/* ─────────────────────────  Formatters  ───────────────────────── */

function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat().format(value);
}

function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  // Endpoints return rates as fractions (0–1).
  return `${(value * 100).toFixed(value >= 0.1 || value === 0 ? 0 : 1)}%`;
}

function formatScore(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  // QA scores are averaged on a 0–1 scale; present as a percentage.
  if (value <= 1.5) return `${Math.round(value * 100)}%`;
  return value.toFixed(1);
}

function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
  return `${Math.round(seconds / 60)}m`;
}

function formatMinutesSaved(minutes: number): string {
  if (minutes <= 0) return "0h";
  if (minutes < 60) return `${Math.round(minutes)}m`;
  const hours = minutes / 60;
  if (hours < 24) return `${hours.toFixed(hours < 10 ? 1 : 0)}h`;
  return `${(hours / 24).toFixed(1)}d`;
}

function toneForRate(rate: number | null): Tone {
  if (rate === null) return "neutral";
  if (rate >= 0.85) return "ok";
  if (rate >= 0.6) return "warn";
  return "danger";
}

function toneForQa(score: number | null | undefined): Tone {
  if (score === null || score === undefined) return "neutral";
  const normalized = score <= 1.5 ? score : score / 100;
  if (normalized >= 0.9) return "ok";
  if (normalized >= 0.75) return "warn";
  return "danger";
}

function toneForEscalation(rate: number | null | undefined): Tone {
  if (rate === null || rate === undefined) return "neutral";
  if (rate <= 0.1) return "ok";
  if (rate <= 0.25) return "warn";
  return "danger";
}
