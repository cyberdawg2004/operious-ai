"use client";

import { useCallback, useMemo, useState } from "react";
import {
  Check,
  ChevronDown,
  ChevronRight,
  Clock,
  FileText,
  Play,
  ShieldAlert,
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
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PendingIntegrationState,
} from "@/components/data-state";

type FilterStatus = "all" | ApprovalRecord["status"];
type SortOption = "confidence" | "age" | "evidence";

const filterOptions: { id: FilterStatus; label: string }[] = [
  { id: "all", label: "All" },
  { id: "pending_review", label: "Pending" },
  { id: "approved", label: "Approved" },
  { id: "rejected", label: "Rejected" },
  { id: "applied", label: "Applied" },
];

const sortOptions: { id: SortOption; label: string }[] = [
  { id: "confidence", label: "Confidence" },
  { id: "age", label: "Age" },
  { id: "evidence", label: "Evidence count" },
];

type CognitionHubProps = {
  onOpenTrace?: (traceId: string) => void;
  onOpenKnowledge?: (documentId?: string) => void;
};

export function CognitionHub({ onOpenTrace, onOpenKnowledge }: CognitionHubProps) {
  const [activeFilter, setActiveFilter] = useState<FilterStatus>("all");
  const [sortBy, setSortBy] = useState<SortOption>("confidence");
  const [showSortDropdown, setShowSortDropdown] = useState(false);
  const [pendingNotice, setPendingNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyApprovalId, setBusyApprovalId] = useState<string | null>(null);

  const loadApprovals = useCallback(
    () => listApprovalRecords({ limit: 100, offset: 0 }),
    []
  );
  const { data, error, isLoading, reload } = useApiResource(loadApprovals);

  const approvals = useMemo(() => data?.items ?? [], [data?.items]);
  const filteredRecords = approvals.filter((record) => {
    if (activeFilter === "all") return true;
    return record.status === activeFilter;
  });

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
              approvals.reduce((acc, record) => acc + record.confidence, 0) /
                approvals.length *
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
    <div className="flex-1 bg-[var(--canvas)] py-8 px-12 overflow-auto">
      <div className="mb-6">
        <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-[var(--ink-tertiary)]">
          COGNITION · APPROVAL QUEUE
        </span>
      </div>

      <div className="flex items-center justify-between mb-6">
        <h1 className="font-serif font-bold text-[32px] text-[var(--ink-primary)]">
          Cognition Hub
        </h1>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1 p-1 bg-[var(--surface)] rounded-lg border border-[var(--border-subtle)]">
            {filterOptions.map((option) => (
              <button
                key={option.id}
                onClick={() => setActiveFilter(option.id)}
                className={cn(
                  "px-3 py-1.5 rounded font-mono text-[11px] uppercase tracking-[0.08em] transition-colors duration-160",
                  activeFilter === option.id
                    ? "bg-[var(--gold-primary)] text-white"
                    : "text-[var(--ink-secondary)] hover:bg-[var(--surface-hover)]"
                )}
              >
                {option.label}
              </button>
            ))}
          </div>

          <div className="relative">
            <button
              onClick={() => setShowSortDropdown(!showSortDropdown)}
              className="flex items-center gap-2 px-3 py-2 bg-[var(--surface)] border border-[var(--border-subtle)] rounded font-mono text-[11px] text-[var(--ink-secondary)] hover:bg-[var(--surface-hover)] transition-colors duration-160"
            >
              Sort: {sortOptions.find((option) => option.id === sortBy)?.label}
              <ChevronDown className="w-3 h-3" />
            </button>
            {showSortDropdown && (
              <div className="absolute top-full right-0 mt-1 w-40 bg-[var(--surface)] border border-[var(--border-subtle)] rounded shadow-lg z-10">
                {sortOptions.map((option) => (
                  <button
                    key={option.id}
                    onClick={() => {
                      setSortBy(option.id);
                      setShowSortDropdown(false);
                    }}
                    className={cn(
                      "w-full px-3 py-2 text-left font-mono text-[11px] hover:bg-[var(--surface-hover)] transition-colors duration-160",
                      sortBy === option.id
                        ? "text-[var(--gold-primary)]"
                        : "text-[var(--ink-secondary)]"
                    )}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {isLoading && <LoadingState label="Loading approval records..." />}

      {error && !isLoading && (
        <ErrorState
          title="Approval records unavailable"
          message={error}
          onAction={reload}
        />
      )}

      {pendingNotice && !isLoading && (
        <div className="mb-6">
          <PendingIntegrationState
            title="Pending integration"
            message={pendingNotice}
            actionLabel="Dismiss"
            onAction={() => setPendingNotice(null)}
          />
        </div>
      )}

      {actionError && !isLoading && (
        <div className="mb-6">
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
          <div className="grid grid-cols-4 gap-4 mb-8">
            <StatCard label="PENDING REVIEW" value={String(stats.pending)} />
            <StatCard label="APPROVED" value={String(stats.approved)} />
            <StatCard label="APPLIED" value={String(stats.applied)} />
            <StatCard label="AVERAGE CONFIDENCE" value={stats.avgConfidence} />
          </div>

          {sortedRecords.length === 0 ? (
            <EmptyState
              title="No approval records"
              message="The SOP intelligence endpoint returned no approval records for the current tenant and filter."
              actionLabel="Refresh"
              onAction={reload}
            />
          ) : (
            <div className="grid grid-cols-2 gap-6">
              {sortedRecords.map((record) => (
                <ApprovalCard
                  key={record.approval_id}
                  record={record}
                  isBusy={busyApprovalId === record.approval_id}
                  onApprove={() => void runLifecycleAction(record.approval_id, "approve")}
                  onApply={() => void runLifecycleAction(record.approval_id, "apply")}
                  onReject={() =>
                    setPendingNotice(
                      "The backend exposes approval and apply endpoints, but no rejection endpoint is currently available for SOP intelligence records."
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
    </div>
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
  const statusConfig = getStatusConfig(record.status);

  return (
    <div className="bg-[var(--surface)] border border-[var(--border-subtle)] rounded-lg p-6 flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <span
          className={cn(
            "px-2.5 py-1 border rounded-full font-mono text-[10px] uppercase tracking-[0.08em]",
            statusConfig.className
          )}
        >
          {statusConfig.label}
        </span>
        <span className="font-mono text-[13px] font-medium tabular-nums text-[var(--ink-secondary)]">
          {Math.round(record.confidence * 100)}% confidence
        </span>
      </div>

      <h3 className="font-serif font-semibold text-lg leading-[1.3] text-[var(--ink-primary)]">
        {record.proposed_change}
      </h3>

      <div>
        <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-[var(--ink-tertiary)] block mb-1">
          AFFECTED DOCUMENT
        </span>
        <button
          onClick={onOpenKnowledge}
          className="font-mono text-[13px] text-[var(--gold-primary)] hover:underline"
        >
          {record.document_id}
        </button>
      </div>

      <div>
        <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-[var(--ink-tertiary)] block mb-2">
          PROPOSED CHANGE
        </span>
        <div className="border border-[var(--border-subtle)] rounded bg-[var(--surface-raised)] p-3">
          <p className="font-mono text-[12px] leading-relaxed text-[var(--ink-secondary)]">
            {record.proposed_change}
          </p>
        </div>
      </div>

      <div>
        <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-[var(--ink-tertiary)] block mb-2">
          SUPPORTING EVIDENCE ({record.evidence_sessions.length})
        </span>
        {record.evidence_sessions.length === 0 ? (
          <p className="font-mono text-[12px] text-[var(--ink-tertiary)]">
            No evidence sessions attached to this record.
          </p>
        ) : (
          <div className="space-y-2">
            {record.evidence_sessions.map((sessionId) => {
              const isExpanded = expandedEvidence === sessionId;
              return (
                <div
                  key={sessionId}
                  className="border border-[var(--border-subtle)] rounded bg-[var(--surface-raised)]"
                >
                  <button
                    onClick={() => setExpandedEvidence(isExpanded ? null : sessionId)}
                    className="w-full flex items-center gap-3 p-3 text-left hover:bg-[var(--surface-hover)] transition-colors duration-160"
                  >
                    {isExpanded ? (
                      <ChevronDown className="w-4 h-4 text-[var(--ink-tertiary)] flex-shrink-0" />
                    ) : (
                      <ChevronRight className="w-4 h-4 text-[var(--ink-tertiary)] flex-shrink-0" />
                    )}
                    <FileText className="w-4 h-4 text-[var(--gold-primary)] flex-shrink-0" />
                    <span className="font-mono text-[12px] text-[var(--ink-secondary)] truncate flex-1">
                      {sessionId}
                    </span>
                  </button>
                  {isExpanded && (
                    <div className="px-3 pb-3 pt-0">
                      <button
                        onClick={() => onOpenTrace?.(sessionId)}
                        className="ml-7 inline-flex items-center gap-2 rounded border border-[var(--border-subtle)] px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.08em] text-[var(--ink-secondary)] hover:border-[var(--gold-primary)] hover:text-[var(--gold-primary)]"
                      >
                        <Play className="h-3 w-3" strokeWidth={1.5} />
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
        <div className="flex items-center gap-3 pt-2 border-t border-[var(--border-subtle)]">
          <button
            onClick={onApprove}
            disabled={isBusy}
            className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 bg-[var(--green-success)] text-white rounded font-mono text-[12px] uppercase tracking-[0.08em] hover:bg-[var(--green-success)]/90 disabled:opacity-50 transition-colors duration-160"
          >
            <Check className="w-4 h-4" strokeWidth={1.5} />
            Approve
          </button>
          <button
            onClick={onReject}
            disabled={isBusy}
            className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 bg-transparent border border-[var(--red-alert)] text-[var(--red-alert)] rounded font-mono text-[12px] uppercase tracking-[0.08em] hover:bg-[var(--red-alert)]/10 disabled:opacity-50 transition-colors duration-160"
          >
            <X className="w-4 h-4" strokeWidth={1.5} />
            Reject
          </button>
        </div>
      )}

      {record.status === "approved" && (
        <button
          onClick={onApply}
          disabled={isBusy}
          className="flex items-center justify-center gap-2 px-4 py-2.5 bg-[var(--gold-primary)] text-white rounded font-mono text-[12px] uppercase tracking-[0.08em] hover:bg-[var(--gold-primary)]/90 disabled:opacity-50 transition-colors duration-160"
        >
          <ShieldAlert className="w-4 h-4" strokeWidth={1.5} />
          Apply to knowledge
        </button>
      )}

      <div className="flex items-center gap-2 text-[var(--ink-tertiary)]">
        <Clock className="w-3 h-3" strokeWidth={1.5} />
        <span className="font-mono text-[10px]">
          Created {formatDateTime(record.created_at)}
        </span>
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-[var(--surface)] border border-[var(--border-subtle)] rounded-lg p-4">
      <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-[var(--ink-tertiary)] block mb-1">
        {label}
      </span>
      <span className="font-mono text-[28px] font-semibold tabular-nums text-[var(--ink-primary)]">
        {value}
      </span>
    </div>
  );
}

function getStatusConfig(status: ApprovalRecord["status"]) {
  switch (status) {
    case "pending_review":
      return {
        label: "PENDING REVIEW",
        className: "border-[var(--warning-amber)] text-[var(--warning-amber)] bg-[var(--warning-amber)]/10",
      };
    case "approved":
      return {
        label: "APPROVED",
        className: "border-[var(--green-success)] text-[var(--green-success)] bg-[var(--green-success)]/10",
      };
    case "rejected":
      return {
        label: "REJECTED",
        className: "border-[var(--red-alert)] text-[var(--red-alert)] bg-[var(--red-alert)]/10",
      };
    case "applied":
      return {
        label: "APPLIED",
        className: "border-[var(--gold-primary)] text-[var(--gold-primary)] bg-[var(--gold-primary)]/10",
      };
  }
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
