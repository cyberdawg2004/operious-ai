"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Check,
  Clock,
  FileText,
  Loader2,
  ShieldCheck,
  X,
} from "lucide-react";
import {
  approveActionApproval,
  denyActionApproval,
  formatApiError,
  getActionApproval,
  listActionApprovals,
  type ActionApprovalDetail,
  type ActionApprovalSummary,
} from "@/lib/api";
import { TechnicalDetails } from "@/components/technical-details";
import { CodeAsReadableText, DownloadableLog } from "@/components/ui/readable-data";
import { useApiResource } from "@/lib/use-api-resource";
import { useAuthSession } from "@/lib/use-auth-session";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-state";

const REFRESH_MS = 30_000;
const APPROVE_CAPABILITY = "tenant.actions.approve";

export function ApprovalInbox({
  embedded = false,
  onCountChange,
}: {
  /** When true, renders without its own page chrome (title + count badge + outer
   * page padding) so it can be composed as a tab inside another shell. */
  embedded?: boolean;
  /** Reports the current pending-approval count, e.g. for a tab badge. */
  onCountChange?: (count: number) => void;
} = {}) {
  const { principal } = useAuthSession();
  // `/auth/me` is the canonical, verified frontend authority source. Missing
  // or failed hydration intentionally fails closed.
  const canApprove = (principal?.capabilities ?? []).includes(APPROVE_CAPABILITY);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ActionApprovalDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<"approve" | "deny" | null>(null);
  const [denyReason, setDenyReason] = useState("");
  const [confirmApprove, setConfirmApprove] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const loadApprovals = useCallback(
    () => listActionApprovals({ status: "pending", limit: 100, offset: 0 }),
    []
  );
  const { data, error, isLoading, reload } = useApiResource(loadApprovals);
  const approvals = useMemo(() => data ?? [], [data]);

  useEffect(() => {
    const interval = window.setInterval(reload, REFRESH_MS);
    return () => window.clearInterval(interval);
  }, [reload]);

  useEffect(() => {
    onCountChange?.(approvals.length);
  }, [approvals.length, onCountChange]);

  useEffect(() => {
    if (selectedId === null) {
      return;
    }
    let active = true;
    const timeout = window.setTimeout(() => {
      setDetailLoading(true);
      setDetailError(null);
      getActionApproval(selectedId)
        .then((loaded) => {
          if (!active) return;
          setDetail(loaded);
        })
        .catch((caught: unknown) => {
          if (!active) return;
          setDetailError(formatApiError(caught));
        })
        .finally(() => {
          if (active) setDetailLoading(false);
        });
    }, 0);
    return () => {
      active = false;
      window.clearTimeout(timeout);
    };
  }, [selectedId]);

  const selectedSummary = useMemo(
    () => approvals.find((approval) => approval.approval_id === selectedId) ?? null,
    [approvals, selectedId]
  );

  const closeDetail = () => {
    setSelectedId(null);
    setDetail(null);
    setDetailError(null);
    setDenyReason("");
    setConfirmApprove(false);
    setActionError(null);
  };

  const runApprove = async () => {
    if (!selectedId || !canApprove) return;
    setBusyAction("approve");
    setActionError(null);
    try {
      await approveActionApproval(selectedId);
      setNotice("Action approved and executed.");
      closeDetail();
      reload();
    } catch (caught: unknown) {
      setActionError(formatApiError(caught));
    } finally {
      setBusyAction(null);
    }
  };

  const runDeny = async () => {
    if (!selectedId || !denyReason.trim() || !canApprove) return;
    setBusyAction("deny");
    setActionError(null);
    try {
      await denyActionApproval(selectedId, denyReason.trim());
      setNotice("Action denied.");
      closeDetail();
      reload();
    } catch (caught: unknown) {
      setActionError(formatApiError(caught));
    } finally {
      setBusyAction(null);
    }
  };

  return (
    <div className={embedded ? "" : "min-h-[calc(100vh-82px)] bg-canvas px-4 py-5 sm:px-6 lg:px-12 lg:py-8"}>
      {!embedded && (
        <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <span className="font-technical text-[10px] uppercase tracking-[0.18em] text-ink-tertiary">
              Governance / Action Sign-offs
            </span>
            <h2 className="mt-1 text-[22px] font-semibold text-ink-primary">
              Action Sign-offs
            </h2>
          </div>
          <div className="inline-flex h-8 items-center gap-2 self-start rounded-md border border-border-subtle bg-surface px-3 font-technical text-[11px] uppercase tracking-[0.10em] text-ink-secondary sm:self-auto">
            <Clock className="h-3.5 w-3.5 text-gold-primary" strokeWidth={1.8} />
            {approvals.length} pending approvals
          </div>
        </div>
      )}

      {notice && (
        <div className="mb-4 flex items-center justify-between gap-3 rounded-md border border-border-subtle bg-surface px-3 py-2 text-[13px] text-ink-primary">
          <span>{notice}</span>
          <button
            type="button"
            onClick={() => setNotice(null)}
            className="flex h-7 w-7 items-center justify-center rounded-md text-ink-tertiary hover:bg-surface-raised hover:text-ink-primary"
            aria-label="Dismiss notification"
          >
            <X className="h-3.5 w-3.5" strokeWidth={1.8} />
          </button>
        </div>
      )}

      {isLoading && <LoadingState label="Loading action approvals..." />}

      {error && !isLoading && (
        <ErrorState
          title="Action approvals unavailable"
          message={error}
          onAction={reload}
        />
      )}

      {!isLoading && !error && approvals.length === 0 && (
        <EmptyState
          title="All caught up — no items need your attention"
          message="Pending manager action approvals will appear here."
          actionLabel="Refresh"
          onAction={reload}
        />
      )}

      {!isLoading && !error && approvals.length > 0 && (
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
          {approvals.map((approval) => (
            <ApprovalCard
              key={approval.approval_id}
              approval={approval}
              active={approval.approval_id === selectedId}
              onOpen={() => setSelectedId(approval.approval_id)}
            />
          ))}
        </div>
      )}

      {selectedId && (
        <ApprovalDetailPanel
          detail={detail}
          summary={selectedSummary}
          loading={detailLoading}
          error={detailError}
          actionError={actionError}
          denyReason={denyReason}
          confirmApprove={confirmApprove}
          busyAction={busyAction}
          onClose={closeDetail}
          onReasonChange={setDenyReason}
          onConfirmApprove={setConfirmApprove}
          onApprove={runApprove}
          onDeny={runDeny}
          canApprove={canApprove}
        />
      )}
    </div>
  );
}

function ApprovalCard({
  approval,
  active,
  onOpen,
}: {
  approval: ActionApprovalSummary;
  active: boolean;
  onOpen: () => void;
}) {
  const confidence = numberFrom(approval.metadata.diagnostic_confidence);
  const category = textFrom(approval.metadata.resolution_category);
  return (
    <button
      type="button"
      onClick={onOpen}
      className={cn(
        "min-h-[156px] rounded-lg border bg-surface p-4 text-left shadow-sm transition-colors hover:border-border-defined hover:bg-surface-raised",
        active ? "border-gold-primary" : "border-border-subtle"
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-gold-primary" strokeWidth={1.8} />
            <span className="truncate text-[15px] font-semibold text-ink-primary">
              {toolLabel(approval.tool_name)}
            </span>
          </div>
          <p className="mt-1 font-technical text-[11px] text-ink-tertiary">
            {shortId(approval.session_id)} / {relativeTime(approval.requested_at)}
          </p>
        </div>
        <span className="rounded border border-border-subtle bg-surface-raised px-2 py-1 font-technical text-[10px] uppercase tracking-[0.10em] text-ink-secondary">
          Pending
        </span>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3">
        <Metric label="Category" value={category ?? "Unknown"} />
        <Metric
          label="Confidence"
          value={confidence === null ? "Unknown" : `${Math.round(confidence * 100)}%`}
        />
      </div>
      <p className="mt-4 line-clamp-2 text-[13px] leading-relaxed text-ink-secondary">
        {payloadSummary(approval.payload)}
      </p>
    </button>
  );
}

function ApprovalDetailPanel({
  detail,
  summary,
  loading,
  error,
  actionError,
  denyReason,
  confirmApprove,
  busyAction,
  onClose,
  onReasonChange,
  onConfirmApprove,
  onApprove,
  onDeny,
  canApprove,
}: {
  detail: ActionApprovalDetail | null;
  summary: ActionApprovalSummary | null;
  loading: boolean;
  error: string | null;
  actionError: string | null;
  denyReason: string;
  confirmApprove: boolean;
  busyAction: "approve" | "deny" | null;
  onClose: () => void;
  onReasonChange: (value: string) => void;
  onConfirmApprove: (value: boolean) => void;
  onApprove: () => void;
  onDeny: () => void;
  canApprove: boolean;
}) {
  const record = detail ?? summary;
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50 backdrop-blur-[2px]">
      <button
        type="button"
        aria-label="Close approval detail overlay"
        className="hidden flex-1 lg:block"
        onClick={onClose}
      />
      <aside className="h-full w-full max-w-[560px] overflow-y-auto border-l border-border-subtle bg-surface shadow-overlay">
        <div className="sticky top-0 z-10 flex min-h-[58px] items-center justify-between border-b border-border-subtle bg-surface px-5">
          <div className="min-w-0">
            <p className="font-technical text-[10px] uppercase tracking-[0.16em] text-ink-tertiary">
              Approval Review
            </p>
            <h3 className="truncate text-[17px] font-semibold text-ink-primary">
              {record ? toolLabel(record.tool_name) : "Action Approval"}
            </h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-9 w-9 items-center justify-center rounded-md border border-border-subtle text-ink-secondary hover:border-border-defined hover:text-ink-primary"
            aria-label="Close approval detail"
          >
            <X className="h-4 w-4" strokeWidth={1.8} />
          </button>
        </div>

        <div className="space-y-5 p-5">
          {loading && (
            <div className="flex h-28 items-center justify-center rounded-lg border border-border-subtle bg-surface-raised">
              <Loader2 className="h-4 w-4 animate-spin text-ink-tertiary" strokeWidth={1.8} />
            </div>
          )}
          {error && <ErrorState title="Approval detail unavailable" message={error} />}
          {actionError && (
            <div className="rounded-md border border-red-alert/30 bg-surface-raised px-3 py-2 text-[13px] text-red-alert">
              {actionError}
            </div>
          )}
          {detail && (
            <>
              <DetailSection
                title="Action Requested"
                icon={<FileText className="h-4 w-4" strokeWidth={1.8} />}
              >
                <KeyValue label="Tool" value={toolLabel(detail.tool_name)} />
                <KeyValue label="Payload" value={payloadSummary(detail.payload)} />
                <TechnicalDetails label="Show full payload" openLabel="Hide full payload">
                  <CodeAsReadableText data={detail.payload} className="mt-2" />
                  <DownloadableLog
                    data={detail.payload}
                    filename={`approval-${detail.approval_id}-payload.json`}
                    label="Download raw payload"
                    className="mt-3"
                  />
                </TechnicalDetails>
              </DetailSection>

              <DetailSection title="Classification">
                <KeyValue
                  label="Category"
                  value={detail.classification_category ?? "Unknown"}
                />
                <KeyValue
                  label="Confidence"
                  value={
                    detail.classification_confidence === null
                      ? "Unknown"
                      : `${Math.round(detail.classification_confidence * 100)}%`
                  }
                />
                <KeyValue
                  label="Summary"
                  value={detail.classification_summary ?? "Not recorded"}
                />
              </DetailSection>

              <DetailSection title="Session">
                <KeyValue label="Session" value={detail.session_id} />
                <KeyValue label="Phase" value={detail.session_phase} />
                <KeyValue label="Opened" value={formatDate(detail.session_opened_at)} />
              </DetailSection>

              <DetailSection title="Governance">
                <KeyValue
                  label="Decision"
                  value={detail.governance_decision_id ?? "Not recorded"}
                />
                <KeyValue
                  label="Reason"
                  value={detail.governance_reason ?? "Not recorded"}
                />
                <KeyValue
                  label="Evaluated"
                  value={
                    detail.governance_evaluated_at
                      ? formatDate(detail.governance_evaluated_at)
                      : "Not recorded"
                  }
                />
              </DetailSection>

              {canApprove ? (
                <>
              <div className="rounded-lg border border-border-subtle bg-surface-raised p-4">
                <label
                  htmlFor="approval-deny-reason"
                  className="font-technical text-[10px] uppercase tracking-[0.14em] text-ink-tertiary"
                >
                  Deny reason
                </label>
                <textarea
                  id="approval-deny-reason"
                  value={denyReason}
                  onChange={(event) => onReasonChange(event.target.value)}
                  className="mt-2 min-h-[88px] w-full resize-y rounded-md border border-border-subtle bg-surface px-3 py-2 text-[13px] text-ink-primary outline-none transition-colors focus:border-gold-primary"
                />
              </div>

              {confirmApprove && (
                <div className="rounded-lg border border-gold-primary/40 bg-gold-bg p-4">
                  <p className="text-[13px] leading-relaxed text-ink-primary">
                    Confirm approval to create the manager governance decision and execute the tool.
                  </p>
                  <div className="mt-3 flex gap-2">
                    <button
                      type="button"
                      onClick={onApprove}
                      disabled={busyAction !== null}
                      className="inline-flex h-9 items-center gap-2 rounded-md bg-green-success px-3 text-[13px] font-semibold text-white disabled:opacity-60"
                    >
                      <Check className="h-4 w-4" strokeWidth={1.8} />
                      Confirm
                    </button>
                    <button
                      type="button"
                      onClick={() => onConfirmApprove(false)}
                      disabled={busyAction !== null}
                      className="h-9 rounded-md border border-border-subtle px-3 text-[13px] text-ink-secondary hover:border-border-defined hover:text-ink-primary disabled:opacity-60"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}

              <div className="flex flex-col gap-2 sm:flex-row">
                <button
                  type="button"
                  onClick={() => onConfirmApprove(true)}
                  disabled={busyAction !== null}
                  className="inline-flex h-10 flex-1 items-center justify-center gap-2 rounded-md bg-green-success px-4 text-[13px] font-semibold uppercase tracking-[0.08em] text-white disabled:opacity-60"
                >
                  <Check className="h-4 w-4" strokeWidth={1.8} />
                  Approve
                </button>
                <button
                  type="button"
                  onClick={onDeny}
                  disabled={busyAction !== null || !denyReason.trim()}
                  className="inline-flex h-10 flex-1 items-center justify-center gap-2 rounded-md border border-red-alert bg-surface px-4 text-[13px] font-semibold uppercase tracking-[0.08em] text-red-alert transition-colors hover:bg-surface-raised disabled:opacity-50"
                >
                  <X className="h-4 w-4" strokeWidth={1.8} />
                  Deny
                </button>
              </div>
                </>
              ) : (
                <div className="rounded-lg border border-border-subtle bg-surface-raised px-4 py-3 text-[13px] text-ink-secondary">
                  Read-only — approval authority not granted
                </div>
              )}
            </>
          )}
        </div>
      </aside>
    </div>
  );
}

function DetailSection({
  title,
  icon,
  children,
}: {
  title: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border border-border-subtle bg-surface-raised p-4">
      <div className="mb-3 flex items-center gap-2 text-ink-primary">
        {icon}
        <h4 className="font-technical text-[11px] font-semibold uppercase tracking-[0.14em]">
          {title}
        </h4>
      </div>
      <div className="space-y-2">{children}</div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border-subtle bg-surface-raised px-3 py-2">
      <p className="font-technical text-[10px] uppercase tracking-[0.12em] text-ink-tertiary">
        {label}
      </p>
      <p className="mt-1 truncate text-[13px] font-semibold text-ink-primary">
        {value}
      </p>
    </div>
  );
}

function KeyValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid gap-1 sm:grid-cols-[120px_1fr]">
      <span className="font-technical text-[10px] uppercase tracking-[0.12em] text-ink-tertiary">
        {label}
      </span>
      <span className="break-words text-[13px] text-ink-primary">{value}</span>
    </div>
  );
}

function toolLabel(toolName: string): string {
  const labels: Record<string, string> = {
    "warranty.claim": "Warranty Claim",
    "replacement.order": "Replacement Order",
    "refund.request": "Refund Request",
    "warehouse.repair.report": "Warehouse Repair Report",
  };
  return labels[toolName] ?? toolName;
}

function payloadSummary(payload: Record<string, unknown>): string {
  const keys = ["order_id", "product_sku", "issue_category", "refund_amount_cents", "severity"];
  const parts = keys
    .map((key) => {
      const value = payload[key];
      if (value === null || value === undefined || typeof value === "object") {
        return null;
      }
      return `${key}: ${String(value)}`;
    })
    .filter((part): part is string => part !== null);
  return parts.length > 0 ? parts.join(", ") : "Structured payload attached.";
}

function shortId(value: string): string {
  return value.length <= 8 ? value : value.slice(0, 8);
}

function numberFrom(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function textFrom(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function relativeTime(value: string): string {
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return "Unknown time";
  const diffMs = Date.now() - timestamp;
  const absMinutes = Math.max(0, Math.round(diffMs / 60_000));
  if (absMinutes < 1) return "Just now";
  if (absMinutes < 60) return `${absMinutes}m ago`;
  const hours = Math.round(absMinutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}
