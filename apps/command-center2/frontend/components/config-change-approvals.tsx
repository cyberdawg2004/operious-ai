"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, Clock, ShieldCheck, X } from "lucide-react";
import {
  approveConfigChangeRequest,
  applyConfigChangeRequest,
  formatApiError,
  listConfigChangeRequests,
  rejectConfigChangeRequest,
  revokeConfigChangeRequest,
  type TenantConfigChangeRequest,
} from "@/lib/api";
import {
  classifyConfigChange,
  filterConfigChangeRequests,
  type ConfigChangeKind,
} from "@/lib/config-change-payloads";
import { useApiResource } from "@/lib/use-api-resource";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-state";
import { TechnicalDetails } from "@/components/technical-details";

const REFRESH_MS = 30_000;

/**
 * Config-change approval surface (Phase 2.5b-ui).
 *
 * This MIRRORS the Approval Inbox (list → detail → approve/reject) but drives
 * the change-request ledger, not the action-approval endpoints (Step 0
 * constraint B). It deliberately shows the full governed lifecycle —
 * PROPOSED → APPROVED → APPLIED — so the operator sees the edit is dual
 * controlled, not instant (constraint D). Approval must come from a different
 * principal than the proposer; the backend enforces that separation of duty.
 */
export function ConfigChangeApprovals() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  // The ledger list endpoint supports `status` only — fetch PROPOSED and
  // APPROVED, then filter by change_type CLIENT-SIDE (constraint C). A
  // server-side change_type filter is a future backend optimization.
  const load = useCallback(async () => {
    const [proposed, approved] = await Promise.all([
      listConfigChangeRequests({ status: "PROPOSED" }),
      listConfigChangeRequests({ status: "APPROVED" }),
    ]);
    return filterConfigChangeRequests([...proposed.items, ...approved.items]);
  }, []);
  const { data, error, isLoading, reload } = useApiResource(load);
  const requests = useMemo(() => data ?? [], [data]);

  useEffect(() => {
    const interval = window.setInterval(reload, REFRESH_MS);
    return () => window.clearInterval(interval);
  }, [reload]);

  const selected = useMemo(
    () => requests.find((request) => request.change_request_id === selectedId) ?? null,
    [requests, selectedId]
  );

  const closeDetail = () => {
    setSelectedId(null);
    setRejectReason("");
    setActionError(null);
  };

  const runAction = async (
    label: string,
    action: (id: string) => Promise<TenantConfigChangeRequest>
  ) => {
    if (!selectedId) return;
    setBusy(true);
    setActionError(null);
    try {
      await action(selectedId);
      setNotice(label);
      closeDetail();
      reload();
    } catch (caught: unknown) {
      setActionError(formatApiError(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-[calc(100vh-82px)] bg-canvas px-4 py-5 sm:px-6 lg:px-12 lg:py-8">
      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <span className="font-technical text-[10px] uppercase tracking-[0.18em] text-ink-tertiary">
            Governance / Configuration Changes
          </span>
          <h2 className="mt-1 text-[22px] font-semibold text-ink-primary">
            Configuration Approvals
          </h2>
        </div>
        <div className="inline-flex h-8 items-center gap-2 self-start rounded-md border border-border-subtle bg-surface px-3 font-technical text-[11px] uppercase tracking-[0.10em] text-ink-secondary sm:self-auto">
          <Clock className="h-3.5 w-3.5 text-gold-primary" strokeWidth={1.8} />
          {requests.length} pending changes
        </div>
      </div>

      <div className="mb-4 rounded-md border border-border-subtle bg-surface-raised px-3 py-2 text-[12px] leading-relaxed text-ink-secondary">
        Dual control: a proposed change must be approved by a{" "}
        <strong>different principal</strong> than the proposer, then applied. The
        lifecycle below is PROPOSED → APPROVED → APPLIED.
      </div>

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

      {isLoading && <LoadingState label="Loading config change requests..." />}
      {error && !isLoading && (
        <ErrorState title="Config changes unavailable" message={error} onAction={reload} />
      )}
      {!isLoading && !error && requests.length === 0 && (
        <EmptyState
          title="No pending config changes"
          message="Proposed connector and action-policy changes awaiting approval will appear here."
          actionLabel="Refresh"
          onAction={reload}
        />
      )}
      {!isLoading && !error && requests.length > 0 && (
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
          {requests.map((request) => (
            <RequestCard
              key={request.change_request_id}
              request={request}
              active={request.change_request_id === selectedId}
              onOpen={() => setSelectedId(request.change_request_id)}
            />
          ))}
        </div>
      )}

      {selected && (
        <DetailPanel
          request={selected}
          busy={busy}
          actionError={actionError}
          rejectReason={rejectReason}
          onReasonChange={setRejectReason}
          onClose={closeDetail}
          onApprove={() =>
            runAction("Change approved — apply it to take effect.", approveConfigChangeRequest)
          }
          onReject={() =>
            runAction("Change rejected.", (id) =>
              rejectConfigChangeRequest(id, rejectReason.trim())
            )
          }
          onApply={() =>
            runAction("Change applied — the new version is now live.", applyConfigChangeRequest)
          }
          onRevoke={() =>
            runAction("Approval revoked.", revokeConfigChangeRequest)
          }
        />
      )}
    </div>
  );
}

function RequestCard({
  request,
  active,
  onOpen,
}: {
  request: TenantConfigChangeRequest;
  active: boolean;
  onOpen: () => void;
}) {
  const kind = classifyConfigChange(request);
  return (
    <button
      type="button"
      onClick={onOpen}
      className={cn(
        "min-h-[140px] rounded-lg border bg-surface p-4 text-left shadow-sm transition-colors hover:border-border-defined hover:bg-surface-raised",
        active ? "border-gold-primary" : "border-border-subtle"
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-gold-primary" strokeWidth={1.8} />
            <span className="truncate text-[15px] font-semibold text-ink-primary">
              {kindLabel(kind)}
            </span>
          </div>
          <p className="mt-1 font-technical text-[11px] text-ink-tertiary">
            {changeSummary(request)} / by {request.proposed_by}
          </p>
        </div>
        <StatusBadge status={request.status} />
      </div>
    </button>
  );
}

function DetailPanel({
  request,
  busy,
  actionError,
  rejectReason,
  onReasonChange,
  onClose,
  onApprove,
  onReject,
  onApply,
  onRevoke,
}: {
  request: TenantConfigChangeRequest;
  busy: boolean;
  actionError: string | null;
  rejectReason: string;
  onReasonChange: (value: string) => void;
  onClose: () => void;
  onApprove: () => void;
  onReject: () => void;
  onApply: () => void;
  onRevoke: () => void;
}) {
  const isProposed = request.status === "PROPOSED";
  const isApproved = request.status === "APPROVED";
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50 backdrop-blur-[2px]">
      <button
        type="button"
        aria-label="Close detail overlay"
        className="hidden flex-1 lg:block"
        onClick={onClose}
      />
      <aside className="h-full w-full max-w-[560px] overflow-y-auto border-l border-border-subtle bg-surface shadow-overlay">
        <div className="sticky top-0 z-10 flex min-h-[58px] items-center justify-between border-b border-border-subtle bg-surface px-5">
          <div className="min-w-0">
            <p className="font-technical text-[10px] uppercase tracking-[0.16em] text-ink-tertiary">
              Config Change Review
            </p>
            <h3 className="truncate text-[17px] font-semibold text-ink-primary">
              {kindLabel(classifyConfigChange(request))}
            </h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-9 w-9 items-center justify-center rounded-md border border-border-subtle text-ink-secondary hover:border-border-defined hover:text-ink-primary"
            aria-label="Close detail"
          >
            <X className="h-4 w-4" strokeWidth={1.8} />
          </button>
        </div>

        <div className="space-y-5 p-5">
          {actionError && (
            <div className="rounded-md border border-red-alert/30 bg-surface-raised px-3 py-2 text-[13px] text-red-alert">
              {actionError}
            </div>
          )}

          <Section title="Lifecycle">
            <Row label="Status" value={request.status} />
            <Row label="Proposed by" value={request.proposed_by} />
            <Row label="Proposed at" value={formatDate(request.proposed_at)} />
            <Row label="Approved by" value={request.approved_by ?? "Not yet approved"} />
            <Row
              label="Approved at"
              value={request.approved_at ? formatDate(request.approved_at) : "—"}
            />
            <Row
              label="Applied at"
              value={request.applied_at ? formatDate(request.applied_at) : "—"}
            />
            {request.rejection_reason && (
              <Row label="Rejection reason" value={request.rejection_reason} />
            )}
          </Section>

          <Section title="Proposed payload (credential-redacted)">
            <TechnicalDetails label="Show proposed payload" openLabel="Hide proposed payload">
              <pre className="max-h-72 overflow-auto rounded-md border border-border-subtle bg-surface p-3 text-[11px] leading-relaxed text-ink-secondary">
                {JSON.stringify(request.proposed_payload, null, 2)}
              </pre>
            </TechnicalDetails>
          </Section>

          {request.outcome_payload && (
            <Section title="Outcome">
              <TechnicalDetails label="Show outcome payload" openLabel="Hide outcome payload">
                <pre className="max-h-56 overflow-auto rounded-md border border-border-subtle bg-surface p-3 text-[11px] leading-relaxed text-ink-secondary">
                  {JSON.stringify(request.outcome_payload, null, 2)}
                </pre>
              </TechnicalDetails>
            </Section>
          )}

          {isProposed && (
            <>
              <div className="rounded-lg border border-border-subtle bg-surface-raised p-4">
                <label
                  htmlFor="config-reject-reason"
                  className="font-technical text-[10px] uppercase tracking-[0.14em] text-ink-tertiary"
                >
                  Reject reason
                </label>
                <textarea
                  id="config-reject-reason"
                  value={rejectReason}
                  onChange={(event) => onReasonChange(event.target.value)}
                  className="mt-2 min-h-[80px] w-full resize-y rounded-md border border-border-subtle bg-surface px-3 py-2 text-[13px] text-ink-primary outline-none transition-colors focus:border-gold-primary"
                />
              </div>
              <div className="flex flex-col gap-2 sm:flex-row">
                <button
                  type="button"
                  onClick={onApprove}
                  disabled={busy}
                  className="inline-flex h-10 flex-1 items-center justify-center gap-2 rounded-md bg-green-success px-4 text-[13px] font-semibold uppercase tracking-[0.08em] text-white disabled:opacity-60"
                >
                  <Check className="h-4 w-4" strokeWidth={1.8} />
                  Approve
                </button>
                <button
                  type="button"
                  onClick={onReject}
                  disabled={busy || !rejectReason.trim()}
                  className="inline-flex h-10 flex-1 items-center justify-center gap-2 rounded-md border border-red-alert bg-surface px-4 text-[13px] font-semibold uppercase tracking-[0.08em] text-red-alert transition-colors hover:bg-surface-raised disabled:opacity-50"
                >
                  <X className="h-4 w-4" strokeWidth={1.8} />
                  Reject
                </button>
              </div>
            </>
          )}

          {isApproved && (
            <div className="flex flex-col gap-2 sm:flex-row">
              <button
                type="button"
                onClick={onApply}
                disabled={busy}
                className="inline-flex h-10 flex-1 items-center justify-center gap-2 rounded-md bg-gold-primary px-4 text-[13px] font-semibold uppercase tracking-[0.08em] text-white disabled:opacity-60"
              >
                <Check className="h-4 w-4" strokeWidth={1.8} />
                Apply
              </button>
              <button
                type="button"
                onClick={onRevoke}
                disabled={busy}
                className="inline-flex h-10 flex-1 items-center justify-center gap-2 rounded-md border border-border-subtle bg-surface px-4 text-[13px] font-semibold uppercase tracking-[0.08em] text-ink-secondary transition-colors hover:text-ink-primary disabled:opacity-50"
              >
                Revoke
              </button>
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-border-subtle bg-surface-raised p-4">
      <h4 className="mb-3 font-technical text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-primary">
        {title}
      </h4>
      <div className="space-y-2">{children}</div>
    </section>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid gap-1 sm:grid-cols-[140px_1fr]">
      <span className="font-technical text-[10px] uppercase tracking-[0.12em] text-ink-tertiary">
        {label}
      </span>
      <span className="break-words text-[13px] text-ink-primary">{value}</span>
    </div>
  );
}

function StatusBadge({ status }: { status: TenantConfigChangeRequest["status"] }) {
  const tone =
    status === "APPLIED"
      ? "border-green-success/40 text-green-success"
      : status === "APPROVED"
        ? "border-gold-primary/40 text-gold-primary"
        : status === "REJECTED" || status === "REVOKED"
          ? "border-red-alert/40 text-red-alert"
          : "border-border-subtle text-ink-secondary";
  return (
    <span
      className={cn(
        "shrink-0 rounded border bg-surface-raised px-2 py-1 font-technical text-[10px] uppercase tracking-[0.10em]",
        tone
      )}
    >
      {status}
    </span>
  );
}

function kindLabel(kind: ConfigChangeKind | null): string {
  if (kind === "connector") return "Connector Config Change";
  if (kind === "action_policy") return "Action Policy Change";
  return "Config Change";
}

function changeSummary(request: TenantConfigChangeRequest): string {
  const payload = request.proposed_payload;
  if (request.change_type === "connector") {
    return `${String(payload.connector_type ?? "connector")} · ${String(payload.tool_name ?? "")}`;
  }
  if (request.change_type === "policy") {
    return String(payload.policy_type ?? "policy");
  }
  return request.change_type;
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}
