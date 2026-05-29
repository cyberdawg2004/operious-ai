"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Clock, Eye, RefreshCcw } from "lucide-react";
import {
  getSupervisorInspection,
  listSupervisorInspections,
  type SupervisorInspectionDetail,
  type SupervisorInspectionSummary,
} from "@/lib/api";
import { useApiResource } from "@/lib/use-api-resource";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-state";
import { cn } from "@/lib/utils";

export function SupervisorInbox() {
  const [selectedInspectionId, setSelectedInspectionId] = useState<string | null>(null);
  const loadInspections = useCallback(
    () => listSupervisorInspections({ status: "risky", limit: 100, offset: 0 }),
    []
  );
  const { data, error, isLoading, reload } = useApiResource(loadInspections);
  const inspections = useMemo(() => data?.items ?? [], [data?.items]);

  const selectedInspection = useMemo(
    () =>
      inspections.find((item) => item.inspection_id === selectedInspectionId) ??
      inspections[0] ??
      null,
    [inspections, selectedInspectionId]
  );

  useEffect(() => {
    const interval = window.setInterval(reload, 60_000);
    return () => window.clearInterval(interval);
  }, [reload]);

  return (
    <div className="min-w-0 flex-1 bg-canvas px-4 py-5 sm:px-6 lg:px-8">
      <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="mb-2 font-mono text-[11px] uppercase tracking-[0.18em] text-gold-primary">
            SUPERVISOR - RISK REVIEW
          </div>
          <h1 className="font-display text-[32px] font-bold text-ink-primary">
            Supervisor Inbox
          </h1>
        </div>
        <button
          type="button"
          onClick={reload}
          className="inline-flex h-10 items-center gap-2 rounded border border-border-subtle px-3 font-technical text-[10px] uppercase tracking-[0.12em] text-ink-secondary transition-colors hover:border-border-defined hover:text-ink-primary"
        >
          <RefreshCcw className="h-3.5 w-3.5" strokeWidth={1.6} />
          Refresh
        </button>
      </div>

      {isLoading && <LoadingState label="Loading supervisor inbox..." />}

      {error && !isLoading && (
        <ErrorState
          title="Supervisor inbox unavailable"
          message={error}
          actionLabel="Retry"
          onAction={reload}
        />
      )}

      {!isLoading && !error && inspections.length === 0 && (
        <EmptyState
          title="No risky inspections"
          message="No supervisor inspections currently match the risky review filter."
          actionLabel="Refresh"
          onAction={reload}
        />
      )}

      {!isLoading && !error && inspections.length > 0 && (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(360px,0.85fr)]">
          <div className="min-w-0 rounded-lg border border-border-subtle bg-surface-raised">
            <div className="grid min-h-11 grid-cols-[minmax(110px,1fr)_minmax(110px,1fr)_90px_90px_130px_72px] items-center gap-3 border-b border-border-subtle px-4 font-mono text-[10px] uppercase tracking-[0.14em] text-ink-tertiary">
              <span>Session</span>
              <span>Category</span>
              <span>QA</span>
              <span>Esc</span>
              <span>Date</span>
              <span />
            </div>
            <div className="divide-y divide-border-subtle">
              {inspections.map((inspection) => (
                <InspectionRow
                  key={inspection.inspection_id}
                  inspection={inspection}
                  selected={inspection.inspection_id === selectedInspection?.inspection_id}
                  onSelect={() => setSelectedInspectionId(inspection.inspection_id)}
                />
              ))}
            </div>
          </div>

          <InspectionDetail inspectionId={selectedInspection?.inspection_id ?? null} />
        </div>
      )}
    </div>
  );
}

function InspectionRow({
  inspection,
  selected,
  onSelect,
}: {
  inspection: SupervisorInspectionSummary;
  selected: boolean;
  onSelect: () => void;
}) {
  const score = inspection.qa_score?.overall_score ?? null;
  return (
    <div
      className={cn(
        "grid min-h-[58px] grid-cols-[minmax(110px,1fr)_minmax(110px,1fr)_90px_90px_130px_72px] items-center gap-3 px-4 text-[13px]",
        selected && "bg-gold-bg"
      )}
    >
      <span className="min-w-0 truncate font-technical text-[12px] text-ink-secondary">
        {shortId(inspection.session_id ?? inspection.inspection_id)}
      </span>
      <span className="min-w-0 truncate text-ink-primary">{formatLabel(inspection.category)}</span>
      <span className={cn("font-technical text-[12px]", scoreColor(score))}>
        {score === null ? "none" : score.toFixed(2)}
      </span>
      <span className="font-technical text-[12px] text-ink-secondary">
        {inspection.escalation_count}
      </span>
      <span
        className="font-technical text-[11px] text-ink-tertiary"
        title={inspection.started_at}
      >
        {formatDate(inspection.started_at)}
      </span>
      <button
        type="button"
        onClick={onSelect}
        className="inline-flex h-9 items-center justify-center gap-1.5 rounded border border-border-subtle px-2 font-technical text-[10px] uppercase tracking-[0.12em] text-ink-secondary transition-colors hover:border-border-defined hover:text-ink-primary"
      >
        <Eye className="h-3.5 w-3.5" strokeWidth={1.6} />
        View
      </button>
    </div>
  );
}

function InspectionDetail({ inspectionId }: { inspectionId: string | null }) {
  const loadDetail = useCallback(async (): Promise<SupervisorInspectionDetail | null> => {
    if (!inspectionId) return null;
    return getSupervisorInspection(inspectionId);
  }, [inspectionId]);
  const { data, error, isLoading } = useApiResource(loadDetail);

  if (!inspectionId) {
    return (
      <div className="rounded-lg border border-border-subtle bg-surface-raised p-5">
        <p className="text-[13px] text-ink-tertiary">No inspection selected.</p>
      </div>
    );
  }
  if (isLoading) {
    return <LoadingState label="Loading inspection detail..." />;
  }
  if (error) {
    return (
      <ErrorState
        title="Inspection detail unavailable"
        message={error}
      />
    );
  }
  if (!data) return null;

  return (
    <div className="min-w-0 rounded-lg border border-border-subtle bg-surface-raised p-5">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-mono text-[11px] uppercase tracking-[0.16em] text-ink-tertiary">
            {shortId(data.inspection_id)}
          </div>
          <h2 className="mt-1 truncate font-display text-[20px] font-semibold text-ink-primary">
            {formatLabel(data.category)}
          </h2>
        </div>
        {data.is_risky ? (
          <AlertTriangle className="h-5 w-5 shrink-0 text-red-500" strokeWidth={1.7} />
        ) : (
          <CheckCircle2 className="h-5 w-5 shrink-0 text-green-500" strokeWidth={1.7} />
        )}
      </div>

      {data.qa_score && <QAScoreBreakdown score={data.qa_score} />}

      <DetailSection title="Findings">
        {data.findings.length === 0 ? (
          <EmptyLine value="No findings recorded" />
        ) : (
          data.findings.map((finding) => (
            <div key={finding.finding_id} className="rounded border border-border-subtle p-3">
              <div className="mb-1 flex items-center justify-between gap-3">
                <span className="font-technical text-[11px] uppercase tracking-[0.12em] text-ink-secondary">
                  {formatLabel(finding.category)}
                </span>
                <span className="font-technical text-[10px] uppercase tracking-[0.12em] text-ink-tertiary">
                  {finding.severity}
                </span>
              </div>
              <p className="text-[13px] leading-relaxed text-ink-primary">{finding.message}</p>
            </div>
          ))
        )}
      </DetailSection>

      <DetailSection title="Evaluations">
        {data.evaluations.map((evaluation) => (
          <MetricLine
            key={`${evaluation.inspection_id}:${evaluation.evaluator_name}`}
            label={formatLabel(evaluation.evaluator_name)}
            value={evaluation.score.toFixed(2)}
          />
        ))}
      </DetailSection>

      <DetailSection title="Training">
        {data.training_recommendations.length === 0 ? (
          <EmptyLine value="No trainer recommendations" />
        ) : (
          data.training_recommendations.map((recommendation) => (
            <div key={recommendation.recommendation_id} className="rounded border border-border-subtle p-3">
              <div className="mb-1 font-technical text-[11px] uppercase tracking-[0.12em] text-ink-secondary">
                {formatLabel(recommendation.category)} - {recommendation.priority}
              </div>
              <p className="text-[13px] leading-relaxed text-ink-primary">
                {recommendation.recommendation}
              </p>
            </div>
          ))
        )}
      </DetailSection>
    </div>
  );
}

function QAScoreBreakdown({ score }: { score: NonNullable<SupervisorInspectionSummary["qa_score"]> }) {
  return (
    <div className="mb-5 rounded border border-border-subtle bg-surface-sunken p-3">
      <div className="mb-3 flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.16em] text-ink-tertiary">
        <Clock className="h-3.5 w-3.5" strokeWidth={1.5} />
        QA Score
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <MetricLine label="Overall" value={score.overall_score.toFixed(2)} valueClassName={scoreColor(score.overall_score)} />
        <MetricLine label="Diagnostic" value={score.diagnostic_accuracy.toFixed(2)} />
        <MetricLine label="Policy" value={score.policy_compliance.toFixed(2)} />
        <MetricLine label="Resolution" value={score.resolution_quality.toFixed(2)} />
      </div>
    </div>
  );
}

function DetailSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-5">
      <div className="mb-2 font-mono text-[11px] uppercase tracking-[0.16em] text-ink-tertiary">
        {title}
      </div>
      <div className="space-y-2">{children}</div>
    </section>
  );
}

function MetricLine({
  label,
  value,
  valueClassName,
}: {
  label: string;
  value: string;
  valueClassName?: string;
}) {
  return (
    <div className="flex min-w-0 items-center justify-between gap-3 rounded border border-border-subtle px-3 py-2">
      <span className="truncate text-[12px] text-ink-secondary">{label}</span>
      <span className={cn("font-technical text-[12px] text-ink-primary", valueClassName)}>
        {value}
      </span>
    </div>
  );
}

function EmptyLine({ value }: { value: string }) {
  return <p className="text-[13px] text-ink-tertiary">{value}</p>;
}

function scoreColor(score: number | null): string {
  if (score === null) return "text-ink-tertiary";
  if (score >= 0.85) return "text-green-500";
  if (score >= 0.75) return "text-amber-500";
  return "text-red-500";
}

function shortId(value: string): string {
  return value.length <= 10 ? value : `${value.slice(0, 8)}...`;
}

function formatLabel(value: string): string {
  return value.replaceAll("_", " ");
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
