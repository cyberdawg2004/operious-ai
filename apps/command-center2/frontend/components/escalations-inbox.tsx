"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, Check, Clock, Lock, ShieldAlert, X } from "lucide-react";
import {
  approveEscalation,
  formatApiError,
  listEscalations,
  rejectEscalation,
  type EscalationRecord,
} from "@/lib/api";
import { useApiResource } from "@/lib/use-api-resource";
import { useAuthSession } from "@/lib/use-auth-session";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-state";
import { TechnicalDetails } from "@/components/technical-details";

const REFRESH_MS = 30_000;
const APPROVE_CAPABILITY = "tenant.actions.approve";

type ConfirmMode = "approve" | "reject" | null;
type HandoffTone = "deny" | "escalate" | "crisis";

/**
 * Escalation Operator Queue (Phase 3-ui) — closes the escalate-not-dead-letter
 * loop. The backend creates an escalation when the diagnostic agent cannot
 * produce a governance-clean answer (a governance DENY of the model output);
 * a human resolves it here.
 *
 * This is an AUTHORITY surface: approving an escalation is a HUMAN-OVERRIDE
 * governance ALLOW (a person overriding a governance DENY). So:
 *   - the approve/reject controls are gated to `tenant.actions.approve` and are
 *     ABSENT (not merely disabled) without it — mirroring the backend gate;
 *   - approve/reject are DELIBERATE: a confirmation step names exactly what is
 *     being overridden before the POST fires.
 * The queue is readable with `tenant.operations.read`; an empty queue is the
 * NORMAL state (this system replaces Tier-1/2 — escalations are rare).
 */
export function EscalationsInbox({
  embedded = false,
  onCountChange,
}: {
  /** When true, renders without its own page chrome (title + count badge + outer
   * page padding) so it can be composed as a tab inside another shell. */
  embedded?: boolean;
  /** Reports the current pending-escalation count, e.g. for a tab badge. */
  onCountChange?: (count: number) => void;
} = {}) {
  const { principal } = useAuthSession();
  const canApprove = (principal?.capabilities ?? []).includes(APPROVE_CAPABILITY);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [confirmMode, setConfirmMode] = useState<ConfirmMode>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [resolvedEscalationIds, setResolvedEscalationIds] = useState<
    ReadonlySet<string>
  >(() => new Set());

  const load = useCallback(
    () => listEscalations({ status: "pending", limit: 50, offset: 0 }),
    []
  );
  const { data, error, isLoading, reload } = useApiResource(load);
  const escalations = useMemo(
    () =>
      [...(data?.items ?? [])]
        .filter((item) => !resolvedEscalationIds.has(item.escalation_id))
        .sort((left, right) => {
          if (left.priority !== right.priority) {
            return left.priority === "high" ? -1 : 1;
          }
          return Date.parse(left.created_at) - Date.parse(right.created_at);
        }),
    [data, resolvedEscalationIds]
  );

  useEffect(() => {
    const interval = window.setInterval(reload, REFRESH_MS);
    return () => window.clearInterval(interval);
  }, [reload]);

  useEffect(() => {
    onCountChange?.(escalations.length);
  }, [escalations.length, onCountChange]);

  const selected = useMemo(
    () => escalations.find((item) => item.escalation_id === selectedId) ?? null,
    [escalations, selectedId]
  );

  const closeDetail = () => {
    setSelectedId(null);
    setConfirmMode(null);
    setNote("");
    setActionError(null);
  };

  const beginConfirm = (mode: ConfirmMode) => {
    setConfirmMode(mode);
    setNote("");
    setActionError(null);
  };

  const runResolution = async () => {
    if (!selectedId || !confirmMode) return;
    const resolvingId = selectedId;
    if (selected && !isDenyOverrideEligible(selected)) {
      setActionError("This handoff is read-only in the DENY override workflow.");
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      if (confirmMode === "approve") {
        await approveEscalation(
          resolvingId,
          note.trim() || "Human override: governance DENY approved by operator."
        );
        setResolvedEscalationIds((current) => {
          const next = new Set(current);
          next.add(resolvingId);
          return next;
        });
        setNotice("Escalation approved and removed from the pending queue.");
      } else {
        await rejectEscalation(resolvingId, note.trim());
        setResolvedEscalationIds((current) => {
          const next = new Set(current);
          next.add(resolvingId);
          return next;
        });
        setNotice("Escalation rejected and removed from the pending queue.");
      }
      closeDetail();
      reload();
    } catch (caught: unknown) {
      setActionError(formatApiError(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={embedded ? "" : "min-h-[calc(100vh-82px)] bg-canvas px-4 py-5 sm:px-6 lg:px-12 lg:py-8"}>
      {!embedded && (
        <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <span className="font-technical text-[10px] uppercase tracking-[0.18em] text-ink-tertiary">
              Governance / Escalations
            </span>
            <h2 className="mt-1 text-[22px] font-semibold text-ink-primary">
              Escalation Queue
            </h2>
          </div>
          <div className="inline-flex h-8 items-center gap-2 self-start rounded-md border border-border-subtle bg-surface px-3 font-technical text-[11px] uppercase tracking-[0.10em] text-ink-secondary sm:self-auto">
            <Clock className="h-3.5 w-3.5 text-gold-primary" strokeWidth={1.8} />
            {escalations.length} pending
          </div>
        </div>
      )}

      <div className="mb-4 rounded-md border border-border-subtle bg-surface-raised px-3 py-2 text-[12px] leading-relaxed text-ink-secondary">
        Each escalation is a case the agent could not auto-resolve within
        governance. Approving one is a{" "}
        <strong>human override of a governance DENY</strong>; rejecting one
        upholds the denial and preserves its lineage. Crisis handoffs are
        high-priority read-only records in this view.
        {!canApprove && (
          <span className="mt-1 flex items-center gap-1.5 font-technical text-[11px] text-ink-tertiary">
            <Lock className="h-3 w-3" strokeWidth={1.8} />
            Read-only: resolving escalations requires the{" "}
            <code className="font-technical">tenant.actions.approve</code>{" "}
            capability.
          </span>
        )}
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

      {isLoading && <LoadingState label="Loading escalations..." />}
      {error && !isLoading && (
        <ErrorState title="Escalations unavailable" message={error} onAction={reload} />
      )}
      {!isLoading && !error && escalations.length === 0 && (
        <EmptyState
          title="All caught up — no items need your attention"
          message="The agent is resolving cases within governance. Anything it cannot safely auto-resolve will appear here for human review."
          actionLabel="Refresh"
          onAction={reload}
        />
      )}
      {!isLoading && !error && escalations.length > 0 && (
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
          {escalations.map((escalation) => (
            <EscalationCard
              key={escalation.escalation_id}
              escalation={escalation}
              active={escalation.escalation_id === selectedId}
              onOpen={() => {
                setSelectedId(escalation.escalation_id);
                setConfirmMode(null);
                setNote("");
                setActionError(null);
              }}
            />
          ))}
        </div>
      )}

      {selected && (
        <DetailPanel
          escalation={selected}
          canApprove={canApprove}
          confirmMode={confirmMode}
          note={note}
          busy={busy}
          actionError={actionError}
          onNoteChange={setNote}
          onBeginConfirm={beginConfirm}
          onCancelConfirm={() => {
            setConfirmMode(null);
            setActionError(null);
          }}
          onConfirm={runResolution}
          onClose={closeDetail}
        />
      )}
    </div>
  );
}

function EscalationCard({
  escalation,
  active,
  onOpen,
}: {
  escalation: EscalationRecord;
  active: boolean;
  onOpen: () => void;
}) {
  const tone = handoffTone(escalation);
  return (
    <button
      type="button"
      onClick={onOpen}
      className={cn(
        "min-h-[120px] rounded-lg border bg-surface p-4 text-left shadow-sm transition-colors hover:border-border-defined hover:bg-surface-raised",
        active ? "border-gold-primary" : "border-border-subtle"
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            {tone === "crisis" ? (
              <AlertTriangle className="h-4 w-4 text-red-alert" strokeWidth={1.9} />
            ) : (
              <ShieldAlert className="h-4 w-4 text-gold-primary" strokeWidth={1.8} />
            )}
            <span className="truncate text-[15px] font-semibold text-ink-primary">
              {handoffTitle(escalation)}
            </span>
          </div>
          <p className="mt-1 line-clamp-2 text-[13px] text-ink-secondary">{escalation.reason}</p>
          <p className="mt-1.5 font-technical text-[11px] text-ink-tertiary">
            session {shortId(escalation.session_id)} / {formatDate(escalation.created_at)}
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2">
          <PriorityBadge escalation={escalation} />
          <StatusBadge status={escalation.status} />
        </div>
      </div>
    </button>
  );
}

function DetailPanel({
  escalation,
  canApprove,
  confirmMode,
  note,
  busy,
  actionError,
  onNoteChange,
  onBeginConfirm,
  onCancelConfirm,
  onConfirm,
  onClose,
}: {
  escalation: EscalationRecord;
  canApprove: boolean;
  confirmMode: ConfirmMode;
  note: string;
  busy: boolean;
  actionError: string | null;
  onNoteChange: (value: string) => void;
  onBeginConfirm: (mode: ConfirmMode) => void;
  onCancelConfirm: () => void;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const isPending = escalation.status === "pending";
  const denyOverrideEligible = isDenyOverrideEligible(escalation);
  const rejectDisabled = busy || (confirmMode === "reject" && !note.trim());
  const canResolve = canApprove && isPending && denyOverrideEligible;

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
              Escalation Review
            </p>
            <h3 className="truncate font-technical text-[14px] font-semibold text-ink-primary">
              {escalation.escalation_id}
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

          <Section title={reasonTitle(escalation)}>
            <p className="text-[13px] leading-relaxed text-ink-primary">{escalation.reason}</p>
          </Section>

          <Section title="Context">
            <Row label="Decision" value={escalation.source_decision ?? "—"} />
            <Row label="Handoff" value={escalation.handoff_kind} />
            <Row label="Priority" value={escalation.priority} />
            <Row label="Created" value={formatDate(escalation.created_at)} />
            <p className="pt-1 font-technical text-[11px] text-ink-tertiary">
              Full grounding (citations, blocked output) is on the originating
              session trace, decision {shortId(escalation.governance_decision_id)}.
            </p>
            <TechnicalDetails label="Show identifiers" openLabel="Hide identifiers">
              <div className="space-y-2">
                <Row label="Session" value={escalation.session_id} mono />
                <Row
                  label="Governance decision"
                  value={escalation.governance_decision_id}
                  mono
                />
              </div>
            </TechnicalDetails>
          </Section>

          <Section title="Lifecycle">
            <Row label="Status" value={escalation.status} />
            <Row label="Resolved by" value={escalation.resolved_by ?? "—"} />
            <Row label="Resolution" value={escalation.resolution ?? "—"} />
            <Row label="Resolved at" value={escalation.resolved_at ? formatDate(escalation.resolved_at) : "—"} />
            {escalation.governance_override_decision_id && (
              <TechnicalDetails label="Show override identifier" openLabel="Hide override identifier">
                <Row
                  label="Override decision"
                  value={escalation.governance_override_decision_id}
                  mono
                />
              </TechnicalDetails>
            )}
          </Section>

          {/* AUTHORITY GATE: approve/reject are ABSENT (not disabled) unless the
              operator holds tenant.actions.approve. Without it, the panel is
              read-only evidence. */}
          {canResolve && confirmMode === null && (
            <div className="space-y-3">
              <p className="text-[12px] leading-relaxed text-ink-secondary">
                Choose a path below. The next step asks you to confirm before
                any state changes are recorded.
              </p>
              <div className="flex flex-col gap-2 sm:flex-row">
                <button
                  type="button"
                  onClick={() => onBeginConfirm("approve")}
                  disabled={busy}
                  className="inline-flex h-10 flex-1 items-center justify-center gap-2 rounded-md bg-green-success px-4 text-[13px] font-semibold uppercase tracking-[0.08em] text-white disabled:opacity-60"
                >
                  <Check className="h-4 w-4" strokeWidth={1.8} />
                  Review override
                </button>
                <button
                  type="button"
                  onClick={() => onBeginConfirm("reject")}
                  disabled={busy}
                  className="inline-flex h-10 flex-1 items-center justify-center gap-2 rounded-md border border-red-alert bg-surface px-4 text-[13px] font-semibold uppercase tracking-[0.08em] text-red-alert transition-colors hover:bg-surface-raised disabled:opacity-50"
                >
                  <X className="h-4 w-4" strokeWidth={1.8} />
                  Review denial
                </button>
              </div>
            </div>
          )}

          {canResolve && confirmMode === "approve" && (
            <div className="rounded-lg border border-gold-primary/50 bg-surface-raised p-4">
              <div className="flex items-center gap-2 text-gold-primary">
                <AlertTriangle className="h-4 w-4" strokeWidth={1.9} />
                <span className="font-technical text-[11px] font-semibold uppercase tracking-[0.12em]">
                  Confirm human override
                </span>
              </div>
              <p className="mt-2 text-[13px] leading-relaxed text-ink-primary">
                You are overriding a governance <strong>DENY</strong> and recording
                a human ALLOW. The blocked decision was:
              </p>
              <p className="mt-2 rounded-md border border-border-subtle bg-surface px-3 py-2 text-[12px] text-ink-secondary">
                {escalation.reason}
              </p>
              <label
                htmlFor="escalation-approve-note"
                className="mt-3 block font-technical text-[10px] uppercase tracking-[0.14em] text-ink-tertiary"
              >
                Resolution note (optional)
              </label>
              <textarea
                id="escalation-approve-note"
                value={note}
                onChange={(event) => onNoteChange(event.target.value)}
                placeholder="Why this override is justified…"
                className="mt-2 min-h-[72px] w-full resize-y rounded-md border border-border-subtle bg-surface px-3 py-2 text-[13px] text-ink-primary outline-none transition-colors focus:border-gold-primary"
              />
              <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                <button
                  type="button"
                  onClick={onConfirm}
                  disabled={busy}
                  className="inline-flex h-10 flex-1 items-center justify-center gap-2 rounded-md bg-green-success px-4 text-[13px] font-semibold uppercase tracking-[0.08em] text-white disabled:opacity-60"
                >
                  <Check className="h-4 w-4" strokeWidth={1.8} />
                  Override DENY now
                </button>
                <button
                  type="button"
                  onClick={onCancelConfirm}
                  disabled={busy}
                  className="inline-flex h-10 items-center justify-center rounded-md border border-border-subtle bg-surface px-4 text-[13px] font-semibold uppercase tracking-[0.08em] text-ink-secondary hover:text-ink-primary disabled:opacity-50"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {canResolve && confirmMode === "reject" && (
            <div className="rounded-lg border border-red-alert/40 bg-surface-raised p-4">
              <div className="flex items-center gap-2 text-red-alert">
                <ShieldAlert className="h-4 w-4" strokeWidth={1.9} />
                <span className="font-technical text-[11px] font-semibold uppercase tracking-[0.12em]">
                  Uphold the DENY
                </span>
              </div>
              <p className="mt-2 text-[13px] leading-relaxed text-ink-primary">
                The denial stands and its lineage is preserved. Record why.
              </p>
              <label
                htmlFor="escalation-reject-reason"
                className="mt-3 block font-technical text-[10px] uppercase tracking-[0.14em] text-ink-tertiary"
              >
                Rejection reason (required)
              </label>
              <textarea
                id="escalation-reject-reason"
                value={note}
                onChange={(event) => onNoteChange(event.target.value)}
                placeholder="Enter a reason to enable the confirm button…"
                className="mt-2 min-h-[72px] w-full resize-y rounded-md border border-border-subtle bg-surface px-3 py-2 text-[13px] text-ink-primary outline-none transition-colors focus:border-red-alert"
              />
              {!note.trim() && (
                <p className="mt-1 text-[11px] text-ink-tertiary">
                  A rejection reason is required before you can confirm.
                </p>
              )}
              <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                <button
                  type="button"
                  onClick={onConfirm}
                  disabled={rejectDisabled}
                  title={!note.trim() ? "Enter a rejection reason above to enable this button" : undefined}
                  className="inline-flex h-10 flex-1 items-center justify-center gap-2 rounded-md border border-red-alert bg-surface px-4 text-[13px] font-semibold uppercase tracking-[0.08em] text-red-alert transition-colors hover:bg-surface-raised disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <X className="h-4 w-4" strokeWidth={1.8} />
                  Uphold DENY now
                </button>
                <button
                  type="button"
                  onClick={onCancelConfirm}
                  disabled={busy}
                  className="inline-flex h-10 items-center justify-center rounded-md border border-border-subtle bg-surface px-4 text-[13px] font-semibold uppercase tracking-[0.08em] text-ink-secondary hover:text-ink-primary disabled:opacity-50"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {canApprove && isPending && !denyOverrideEligible && (
            <div className="flex items-center gap-2 rounded-md border border-red-alert/30 bg-surface-raised px-3 py-2 text-[12px] leading-relaxed text-ink-secondary">
              <AlertTriangle className="h-3.5 w-3.5 text-red-alert" strokeWidth={1.8} />
              This crisis/ESCALATE handoff is visible here for human handling;
              DENY override controls do not apply.
            </div>
          )}

          {!canApprove && (
            <div className="flex items-center gap-2 rounded-md border border-border-subtle bg-surface-raised px-3 py-2 font-technical text-[11px] text-ink-tertiary">
              <Lock className="h-3.5 w-3.5" strokeWidth={1.8} />
              Resolving requires the tenant.actions.approve capability.
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

function Row({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="grid gap-1 sm:grid-cols-[150px_1fr]">
      <span className="font-technical text-[10px] uppercase tracking-[0.12em] text-ink-tertiary">
        {label}
      </span>
      <span className={cn("break-words text-[13px] text-ink-primary", mono && "font-technical text-[12px]")}>
        {value}
      </span>
    </div>
  );
}

function StatusBadge({ status }: { status: EscalationRecord["status"] }) {
  const tone =
    status === "approved"
      ? "border-green-success/40 text-green-success"
      : status === "rejected"
        ? "border-red-alert/40 text-red-alert"
        : status === "reviewed"
          ? "border-gold-primary/40 text-gold-primary"
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

function PriorityBadge({ escalation }: { escalation: EscalationRecord }) {
  const isHigh = escalation.priority === "high";
  const tone =
    escalation.handoff_kind === "crisis"
      ? "border-red-alert/50 text-red-alert"
      : isHigh
        ? "border-gold-primary/50 text-gold-primary"
        : "border-border-subtle text-ink-tertiary";
  return (
    <span
      className={cn(
        "rounded border bg-surface-raised px-2 py-1 font-technical text-[10px] uppercase tracking-[0.10em]",
        tone
      )}
    >
      {escalation.handoff_kind}
      {isHigh ? " / high" : ""}
    </span>
  );
}

function isDenyOverrideEligible(escalation: EscalationRecord): boolean {
  return (
    escalation.handoff_kind === "denial" &&
    (escalation.source_decision ?? "deny") === "deny"
  );
}

function handoffTone(escalation: EscalationRecord): HandoffTone {
  if (escalation.handoff_kind === "crisis") return "crisis";
  if (escalation.source_decision === "escalate") return "escalate";
  return "deny";
}

function handoffTitle(escalation: EscalationRecord): string {
  const tone = handoffTone(escalation);
  if (tone === "crisis") return "CRISIS handoff";
  if (tone === "escalate") return "Governance ESCALATE";
  return "Governance DENY — review";
}

function reasonTitle(escalation: EscalationRecord): string {
  const tone = handoffTone(escalation);
  if (tone === "crisis") return "Why this is crisis-handled";
  if (tone === "escalate") return "Why this was escalated";
  return "Why this was blocked (governance DENY)";
}

function shortId(value: string): string {
  return value.length > 10 ? `${value.slice(0, 8)}…` : value;
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}
