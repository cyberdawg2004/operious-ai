"use client";

import { useCallback, useMemo, useState } from "react";
import {
  Check,
  ChevronDown,
  ChevronRight,
  Clock,
  FileText,
  Play,
  RefreshCw,
  Search,
  Sparkles,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  applyApproval,
  approveApproval,
  formatApiError,
  listApprovalRecords,
  type ApprovalRecord,
} from "@/lib/api";
import { useApiResource } from "@/lib/use-api-resource";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CodeAsReadableText, DownloadableLog } from "@/components/ui/readable-data";
import { StatusBadge, type StatusTone } from "@/components/ui/status-badge";
import { TechnicalDetails } from "@/components/technical-details";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PendingIntegrationState,
} from "@/components/data-state";

type FilterStatus = "all" | ApprovalRecord["status"];
type ProposalSourceFilter = "all" | "quality" | "failure_pattern";
type SortOption = "confidence" | "age" | "evidence";

const sourceFilterOptions: { id: ProposalSourceFilter; label: string }[] = [
  { id: "all", label: "All proposals" },
  { id: "quality", label: "Quality improvements" },
  { id: "failure_pattern", label: "From failure patterns" },
];

const filterOptions: { id: FilterStatus; label: string }[] = [
  { id: "all", label: "All statuses" },
  { id: "pending_review", label: "Pending review" },
  { id: "approved", label: "Approved" },
  { id: "rejected", label: "Rejected" },
  { id: "applied", label: "Applied" },
];

const sortOptions: { id: SortOption; label: string }[] = [
  { id: "confidence", label: "Sort by confidence" },
  { id: "age", label: "Sort by age" },
  { id: "evidence", label: "Sort by evidence count" },
];

const statusMeta: Record<ApprovalRecord["status"], { label: string; tone: StatusTone }> = {
  pending_review: { label: "Pending review", tone: "warning" },
  approved: { label: "Approved", tone: "info" },
  rejected: { label: "Rejected", tone: "danger" },
  applied: { label: "Applied", tone: "success" },
};

type CognitionHubProps = {
  onOpenTrace?: (traceId: string) => void;
  onOpenKnowledge?: (documentId?: string) => void;
};

export function CognitionHub({ onOpenTrace, onOpenKnowledge }: CognitionHubProps) {
  const [activeFilter, setActiveFilter] = useState<FilterStatus>("all");
  const [activeSourceFilter, setActiveSourceFilter] =
    useState<ProposalSourceFilter>("all");
  const [sortBy, setSortBy] = useState<SortOption>("confidence");
  const [pendingNotice, setPendingNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyApprovalId, setBusyApprovalId] = useState<string | null>(null);

  const loadApprovals = useCallback(
    () => listApprovalRecords({ limit: 100, offset: 0 }),
    []
  );
  const { data, error, isLoading, reload } = useApiResource(loadApprovals);

  const approvals = useMemo(() => data?.items ?? [], [data?.items]);
  const filteredRecords = useMemo(
    () =>
      approvals.filter((record) => {
        const isFailurePattern = record.metadata?.failure_pattern === true;
        if (activeSourceFilter === "failure_pattern" && !isFailurePattern) {
          return false;
        }
        if (activeSourceFilter === "quality" && isFailurePattern) {
          return false;
        }
        if (activeFilter === "all") return true;
        return record.status === activeFilter;
      }),
    [activeFilter, activeSourceFilter, approvals]
  );

  const sortedRecords = useMemo(() => {
    return [...filteredRecords].sort((a, b) => {
      switch (sortBy) {
        case "confidence":
          return b.confidence - a.confidence;
        case "age":
          return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
        case "evidence":
          return b.evidence_sessions.length - a.evidence_sessions.length;
      }
    });
  }, [filteredRecords, sortBy]);

  const stats = useMemo(
    () => ({
      pending: approvals.filter((record) => record.status === "pending_review").length,
      approved: approvals.filter((record) => record.status === "approved").length,
      applied: approvals.filter((record) => record.status === "applied").length,
      avgConfidence:
        approvals.length === 0
          ? "No data"
          : `${Math.round(
              (approvals.reduce((acc, record) => acc + record.confidence, 0) /
                approvals.length) *
                100
            )}%`,
    }),
    [approvals]
  );

  const runLifecycleAction = async (
    approvalId: string,
    action: "approve" | "apply"
  ) => {
    setBusyApprovalId(approvalId);
    setActionError(null);
    setPendingNotice(null);
    try {
      if (action === "approve") {
        await approveApproval(approvalId);
      } else {
        await applyApproval(approvalId);
      }
      reload();
    } catch (caught: unknown) {
      setActionError(formatApiError(caught));
    } finally {
      setBusyApprovalId(null);
    }
  };

  return (
    <main className="min-w-0 flex-1 overflow-auto bg-canvas px-4 py-5 sm:px-6 lg:px-8">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <p className="text-meta">Agent proposals from quality reviews and failure patterns</p>

        <div className="flex flex-col gap-3 md:flex-row md:items-center">
          <label className="flex flex-col gap-1">
            <span className="sr-only">Status</span>
            <select
              value={activeFilter}
              onChange={(event) => setActiveFilter(event.target.value as FilterStatus)}
              className="cc-select h-10 min-w-[160px]"
            >
              {filterOptions.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1">
            <span className="sr-only">Source</span>
            <select
              value={activeSourceFilter}
              onChange={(event) => setActiveSourceFilter(event.target.value as ProposalSourceFilter)}
              className="cc-select h-10 min-w-[180px]"
            >
              {sourceFilterOptions.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1">
            <span className="sr-only">Sort</span>
            <select
              value={sortBy}
              onChange={(event) => setSortBy(event.target.value as SortOption)}
              className="cc-select h-10 min-w-[180px]"
            >
              {sortOptions.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>

          <button
            type="button"
            onClick={reload}
            className="cc-btn cc-btn-secondary h-10 w-10"
            aria-label="Refresh recommendations"
          >
            <RefreshCw size={14} strokeWidth={1.8} className={cn(isLoading && "animate-spin")} />
          </button>

          <button
            type="button"
            disabled
            title="Conversational knowledge-base analysis will be available in a future update"
            className="cc-btn cc-btn-secondary h-10 opacity-50"
          >
            <Sparkles size={14} strokeWidth={1.8} />
            Analyze knowledge base
          </button>
        </div>
      </div>

      {isLoading && <div className="mt-8"><LoadingState label="Loading approval records..." /></div>}

      {error && !isLoading && (
        <div className="mt-8">
          <ErrorState title="Approval records unavailable" message={error} onAction={reload} />
        </div>
      )}

      {pendingNotice && !isLoading && (
        <div className="mt-6">
          <PendingIntegrationState
            title="Pending integration"
            message={pendingNotice}
            actionLabel="Dismiss"
            onAction={() => setPendingNotice(null)}
          />
        </div>
      )}

      {actionError && !isLoading && (
        <div className="mt-6">
          <ErrorState
            title="Lifecycle action failed"
            message={actionError}
            actionLabel="Dismiss"
            onAction={() => setActionError(null)}
          />
        </div>
      )}

      {data && !isLoading && !error && (
        <>
          <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard label="Pending review" value={String(stats.pending)} />
            <StatCard label="Approved" value={String(stats.approved)} />
            <StatCard label="Applied" value={String(stats.applied)} />
            <StatCard label="Average confidence" value={stats.avgConfidence} />
          </div>

          {sortedRecords.length === 0 ? (
            <div className="mt-6">
              <EmptyState
                title="No recommendations right now"
                message="The SOP intelligence engine hasn't proposed any changes for the current tenant and filters."
                actionLabel="Refresh"
                onAction={reload}
              />
            </div>
          ) : (
            <div className="mt-6 grid grid-cols-1 gap-4 xl:grid-cols-2 xl:gap-6">
              {sortedRecords.map((record) => (
                <ApprovalCard
                  key={record.approval_id}
                  record={record}
                  isBusy={busyApprovalId === record.approval_id}
                  onApprove={() => void runLifecycleAction(record.approval_id, "approve")}
                  onApply={() => void runLifecycleAction(record.approval_id, "apply")}
                  onReject={() =>
                    setPendingNotice(
                      "Rejecting these suggestions is not available in this screen yet."
                    )
                  }
                  onOpenTrace={onOpenTrace}
                  onOpenKnowledge={() => onOpenKnowledge?.(record.document_id)}
                />
              ))}
            </div>
          )}
        </>
      )}
    </main>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{label}</CardTitle>
      </CardHeader>
      <p className="heading-page tabular">{value}</p>
    </Card>
  );
}

function ApprovalCard({
  record,
  isBusy,
  onApprove,
  onApply,
  onReject,
  onOpenTrace,
  onOpenKnowledge,
}: {
  record: ApprovalRecord;
  isBusy: boolean;
  onApprove: () => void;
  onApply: () => void;
  onReject: () => void;
  onOpenTrace?: (traceId: string) => void;
  onOpenKnowledge: () => void;
}) {
  const [expandedEvidence, setExpandedEvidence] = useState<string | null>(null);
  const meta = statusMeta[record.status];
  const isFailurePattern = record.metadata?.failure_pattern === true;
  const confidencePct = Math.round(record.confidence * 100);

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge label={meta.label} tone={meta.tone} />
          {isFailurePattern && (
            <StatusBadge label="From failure pattern" tone="neutral" icon={Search} />
          )}
        </div>
        <StatusBadge label={`${confidencePct}% confidence`} tone={confidenceTone(record.confidence)} />
      </div>

      <h3 className="mt-3 heading-section text-[15px] leading-snug">{record.proposed_change}</h3>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button type="button" onClick={onOpenKnowledge} className="cc-btn cc-btn-secondary">
          <FileText size={13} strokeWidth={1.8} />
          View affected document
        </button>
      </div>

      <div className="mt-4">
        <CardDescription>
          Supporting evidence ({record.evidence_sessions.length} session{record.evidence_sessions.length === 1 ? "" : "s"})
        </CardDescription>
        {record.evidence_sessions.length === 0 ? (
          <p className="mt-2 text-meta">No evidence sessions attached to this record.</p>
        ) : (
          <div className="mt-2 space-y-2">
            {record.evidence_sessions.map((sessionId, index) => {
              const isExpanded = expandedEvidence === sessionId;
              return (
                <div key={sessionId} className="rounded-md border border-border-subtle bg-surface-raised">
                  <button
                    type="button"
                    onClick={() => setExpandedEvidence(isExpanded ? null : sessionId)}
                    className="flex min-h-10 w-full items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-surface"
                  >
                    {isExpanded ? (
                      <ChevronDown size={14} strokeWidth={1.8} className="shrink-0 text-ink-tertiary" />
                    ) : (
                      <ChevronRight size={14} strokeWidth={1.8} className="shrink-0 text-ink-tertiary" />
                    )}
                    <span className="text-[13px] text-ink-secondary">Session {index + 1}</span>
                    <span className="ml-auto truncate text-meta">{sessionId}</span>
                  </button>
                  {isExpanded && (
                    <div className="px-3 pb-3">
                      <button
                        type="button"
                        onClick={() => onOpenTrace?.(sessionId)}
                        className="cc-btn cc-btn-ghost"
                      >
                        <Play size={13} strokeWidth={1.8} />
                        Open trace
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {record.status === "pending_review" && (
        <div className="mt-4 flex flex-col gap-2 border-t border-border-subtle pt-3 sm:flex-row">
          <button type="button" onClick={onApprove} disabled={isBusy} className="cc-btn cc-btn-primary flex-1">
            <Check size={14} strokeWidth={1.8} />
            Approve
          </button>
          <button type="button" onClick={onReject} disabled={isBusy} className="cc-btn cc-btn-secondary flex-1">
            <X size={14} strokeWidth={1.8} />
            Reject
          </button>
        </div>
      )}

      {record.status === "approved" && (
        <div className="mt-4 border-t border-border-subtle pt-3">
          <button type="button" onClick={onApply} disabled={isBusy} className="cc-btn cc-btn-primary">
            <Check size={14} strokeWidth={1.8} />
            Apply to knowledge
          </button>
        </div>
      )}

      <div className="mt-4 flex items-center gap-1.5 text-meta">
        <Clock size={12} strokeWidth={1.8} />
        Created {formatDateTime(record.created_at)}
      </div>

      <TechnicalDetails label="Show details" openLabel="Hide details" className="mt-3">
        <CodeAsReadableText
          data={{
            approval_id: record.approval_id,
            document_id: record.document_id,
            proposed_by: record.proposed_by,
            reviewed_by: record.reviewed_by,
            evidence_sessions: record.evidence_sessions,
            metadata: record.metadata ?? {},
          }}
        />
        <DownloadableLog
          data={record}
          filename={`approval-${record.approval_id}.json`}
          label="Download approval record"
          className="mt-3"
        />
      </TechnicalDetails>
    </Card>
  );
}

function confidenceTone(confidence: number): StatusTone {
  if (confidence >= 0.8) return "success";
  if (confidence >= 0.5) return "warning";
  return "danger";
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Invalid date";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}
