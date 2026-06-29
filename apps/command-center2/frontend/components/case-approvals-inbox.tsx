"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Ban,
  BadgeCheck,
  Check,
  CircleHelp,
  Clock,
  FileText,
  Lock,
  MessageSquarePlus,
  ShieldCheck,
  Sparkles,
  X,
  XCircle,
} from "lucide-react";
import {
  approveCaseApproval,
  escalateCaseApproval,
  formatApiError,
  guideCaseApproval,
  listCaseApprovals,
  rejectCaseApproval,
  type ApiPage,
  type CaseApprovalRecord,
  type CaseApprovalStatus,
} from "@/lib/api";
import { useApiResource } from "@/lib/use-api-resource";
import { useAuthSession } from "@/lib/use-auth-session";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-state";
import { TechnicalDetails } from "@/components/technical-details";

const REFRESH_MS = 30_000;
const READ_CAPABILITY = "tenant.approvals.read";
const APPROVE_CAPABILITY = "tenant.actions.approve";
const GUIDE_CAPABILITY = "tenant.resolution.guide";

type DetailMode = "review" | "approve" | "reject" | "guide" | "escalate";

const OPEN_STATUSES: ReadonlySet<CaseApprovalStatus> = new Set([
  "pending_sme_review",
  "awaiting_approval",
  "guidance_in_progress",
]);

/**
 * Case-Approval Queue (Fix 1b human front door) — the APPROVAL surface, NOT
 * escalation. The backend creates an SME-AI-reviewed approval case when a
 * resolution needs human sign-off (REQUIRE_APPROVAL / refund / low-confidence /
 * coordination human-review / crisis action). The operator either:
 *   - APPROVES the recommendation — a deliberate authority action that lets the
 *     resolution proceed (and fires any bound action); or
 *   - GUIDES — submits a prompt; the agent re-proposes ONCE (bounded), and the
 *     re-proposal STILL re-runs governance backend-side (a human cannot force an
 *     ungrounded resolution); or
 *   - ESCALATES — hands the case to the escalation queue.
 *
 * This is an AUTHORITY surface, gated exactly like the escalation queue:
 *   - the QUEUE READ is gated to `tenant.approvals.read`;
 *   - the APPROVE control is gated to `tenant.actions.approve`;
 *   - the GUIDE control is gated to `tenant.resolution.guide`;
 * controls are ABSENT (not merely disabled) without the capability.
 */
export function CaseApprovalsInbox({
  embedded = false,
  onCountChange,
}: {
  /** When true, renders without its own page chrome (title + count badge + outer
   * page padding) so it can be composed as a tab inside another shell. */
  embedded?: boolean;
  /** Reports the current open-case count, e.g. for a tab badge. */
  onCountChange?: (count: number) => void;
} = {}) {
  const { principal } = useAuthSession();
  const capabilities = principal?.capabilities ?? [];
  const canRead = capabilities.includes(READ_CAPABILITY);
  const canApprove = capabilities.includes(APPROVE_CAPABILITY);
  const canGuide = capabilities.includes(GUIDE_CAPABILITY);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<CaseApprovalRecord | null>(null);
  const [mode, setMode] = useState<DetailMode>("review");
  const [note, setNote] = useState("");
  const [guidance, setGuidance] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // The queue read is itself an authority surface: without
  // tenant.approvals.read we do not fetch — the backend would 403 — and render
  // a refusal instead. Hooks below are declared unconditionally (Rules of Hooks)
  // and simply no-op when canRead is false.
  const load = useCallback(
    (): Promise<ApiPage<CaseApprovalRecord>> =>
      canRead
        ? listCaseApprovals({ limit: 50, offset: 0 })
        : Promise.resolve({ items: [], total: 0, limit: 50, offset: 0 }),
    [canRead]
  );
  const { data, error, isLoading, reload } = useApiResource(load);

  const cases = useMemo(
    () =>
      [...(data?.items ?? [])]
        .filter((item) => OPEN_STATUSES.has(item.status))
        .sort((left, right) => {
          const leftAwaiting = left.status === "awaiting_approval" ? 0 : 1;
          const rightAwaiting = right.status === "awaiting_approval" ? 0 : 1;
          if (leftAwaiting !== rightAwaiting) return leftAwaiting - rightAwaiting;
          return Date.parse(left.requested_at) - Date.parse(right.requested_at);
        }),
    [data]
  );

  useEffect(() => {
    if (!canRead) return;
    const interval = window.setInterval(reload, REFRESH_MS);
    return () => window.clearInterval(interval);
  }, [reload, canRead]);

  useEffect(() => {
    onCountChange?.(cases.length);
  }, [cases.length, onCountChange]);

  const openDetail = (record: CaseApprovalRecord) => {
    setSelectedId(record.approval_case_id);
    setDetail(record);
    setMode("review");
    setNote("");
    setGuidance("");
    setActionError(null);
  };

  const closeDetail = () => {
    setSelectedId(null);
    setDetail(null);
    setMode("review");
    setNote("");
    setGuidance("");
    setActionError(null);
  };

  const runApprove = async () => {
    if (!selectedId) return;
    setBusy(true);
    setActionError(null);
    try {
      await approveCaseApproval(selectedId, note.trim() || null);
      setNotice("Case approved — the recommendation proceeds.");
      closeDetail();
      reload();
    } catch (caught: unknown) {
      setActionError(formatApiError(caught));
    } finally {
      setBusy(false);
    }
  };

  const runGuide = async () => {
    if (!selectedId || !guidance.trim()) return;
    setBusy(true);
    setActionError(null);
    try {
      const updated = await guideCaseApproval(selectedId, guidance.trim());
      // The bounded re-proposal returns the revised case (still governed).
      setDetail(updated);
      setMode("review");
      setGuidance("");
      setNotice(
        "Guidance submitted — the agent re-proposed under governance. Review the revised recommendation."
      );
      reload();
    } catch (caught: unknown) {
      setActionError(formatApiError(caught));
    } finally {
      setBusy(false);
    }
  };

  const runEscalate = async () => {
    if (!selectedId || !note.trim()) return;
    setBusy(true);
    setActionError(null);
    try {
      await escalateCaseApproval(selectedId, note.trim());
      setNotice("Case escalated to the escalation queue for human handling.");
      closeDetail();
      reload();
    } catch (caught: unknown) {
      setActionError(formatApiError(caught));
    } finally {
      setBusy(false);
    }
  };

  const runReject = async () => {
    if (!selectedId) return;
    setBusy(true);
    setActionError(null);
    try {
      await rejectCaseApproval(selectedId, note.trim() || null);
      setNotice("Case rejected — no action fires; the denial is recorded.");
      closeDetail();
      reload();
    } catch (caught: unknown) {
      setActionError(formatApiError(caught));
    } finally {
      setBusy(false);
    }
  };

  if (!canRead) {
    return (
      <div className={embedded ? "" : "min-h-[calc(100vh-82px)] bg-canvas px-4 py-5 sm:px-6 lg:px-12 lg:py-8"}>
        {!embedded && <Header count={0} />}
        <div className="flex items-center gap-2 rounded-md border border-border-subtle bg-surface-raised px-3 py-3 font-technical text-[12px] text-ink-tertiary">
          <Lock className="h-3.5 w-3.5" strokeWidth={1.8} />
          Viewing the case-approval queue requires the{" "}
          <code className="font-technical">tenant.approvals.read</code> capability.
        </div>
      </div>
    );
  }

  return (
    <div className={embedded ? "" : "min-h-[calc(100vh-82px)] bg-canvas px-4 py-5 sm:px-6 lg:px-12 lg:py-8"}>
      {!embedded && <Header count={cases.length} />}

      <div className="mb-4 rounded-md border border-border-subtle bg-surface-raised px-3 py-2 text-[12px] leading-relaxed text-ink-secondary">
        Each case is an <strong>SME-AI-recommended resolution awaiting human
        sign-off</strong> — not an escalation. Approving lets the recommendation
        proceed (and fires any bound action); guiding submits one bounded
        re-proposal that still re-runs governance; escalating hands the case to
        the escalation queue.
        {!canApprove && !canGuide && (
          <span className="mt-1 flex items-center gap-1.5 font-technical text-[11px] text-ink-tertiary">
            <Lock className="h-3 w-3" strokeWidth={1.8} />
            Read-only: approving requires{" "}
            <code className="font-technical">tenant.actions.approve</code>, guiding
            requires <code className="font-technical">tenant.resolution.guide</code>.
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

      {isLoading && <LoadingState label="Loading approval cases..." />}
      {error && !isLoading && (
        <ErrorState title="Approval queue unavailable" message={error} onAction={reload} />
      )}
      {!isLoading && !error && cases.length === 0 && (
        <EmptyState
          title="All caught up — no items need your attention"
          message="The agent is resolving cases within governance. Anything that needs human sign-off will appear here for review."
          actionLabel="Refresh"
          onAction={reload}
        />
      )}
      {!isLoading && !error && cases.length > 0 && (
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
          {cases.map((record) => (
            <CaseCard
              key={record.approval_case_id}
              record={record}
              active={record.approval_case_id === selectedId}
              onOpen={() => openDetail(record)}
            />
          ))}
        </div>
      )}

      {detail && (
        <DetailPanel
          record={detail}
          canApprove={canApprove}
          canGuide={canGuide}
          mode={mode}
          note={note}
          guidance={guidance}
          busy={busy}
          actionError={actionError}
          onNoteChange={setNote}
          onGuidanceChange={setGuidance}
          onSetMode={(next) => {
            setMode(next);
            setNote("");
            setGuidance("");
            setActionError(null);
          }}
          onApprove={runApprove}
          onReject={runReject}
          onGuide={runGuide}
          onEscalate={runEscalate}
          onClose={closeDetail}
        />
      )}
    </div>
  );
}

function Header({ count }: { count: number }) {
  return (
    <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <span className="font-technical text-[10px] uppercase tracking-[0.18em] text-ink-tertiary">
          Governance / Message Approvals
        </span>
        <h2 className="mt-1 text-[22px] font-semibold text-ink-primary">
          Message Approvals
        </h2>
      </div>
      <div className="inline-flex h-8 items-center gap-2 self-start rounded-md border border-border-subtle bg-surface px-3 font-technical text-[11px] uppercase tracking-[0.10em] text-ink-secondary sm:self-auto">
        <Clock className="h-3.5 w-3.5 text-gold-primary" strokeWidth={1.8} />
        {count} awaiting
      </div>
    </div>
  );
}

function CaseCard({
  record,
  active,
  onOpen,
}: {
  record: CaseApprovalRecord;
  active: boolean;
  onOpen: () => void;
}) {
  const recommendation = smeRecommendation(record);
  const eligibility = warrantyRefundEligibility(record);
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
            <Sparkles className="h-4 w-4 text-gold-primary" strokeWidth={1.8} />
            <span className="truncate text-[15px] font-semibold text-ink-primary">
              {categoryTitle(record.entry_category)}
            </span>
          </div>
          {eligibility ? (
            <p className="mt-1 line-clamp-2 text-[13px] text-ink-secondary">
              {humanize(eligibility.claimType)}
              {record.product ? ` · ${record.product}` : ""}
              {eligibility.verdict === "eligible" && eligibility.recommendedRemedy
                ? ` · recommends ${humanize(eligibility.recommendedRemedy)}`
                : ""}
            </p>
          ) : (
            <p className="mt-1 line-clamp-2 text-[13px] text-ink-secondary">
              {recommendation?.recommended_reply ||
                record.issue_summary ||
                "SME review in progress…"}
            </p>
          )}
          <p className="mt-1.5 font-technical text-[11px] text-ink-tertiary">
            {record.session_id ? `session ${shortId(record.session_id)} / ` : ""}
            {formatDate(record.requested_at)}
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2">
          {eligibility && <VerdictBadge verdict={eligibility.verdict} />}
          {record.guidance_round > 0 && (
            <span className="rounded border border-gold-primary/50 bg-surface-raised px-2 py-1 font-technical text-[10px] uppercase tracking-[0.10em] text-gold-primary">
              guided
            </span>
          )}
          <StatusBadge status={record.status} />
        </div>
      </div>
    </button>
  );
}

function DetailPanel({
  record,
  canApprove,
  canGuide,
  mode,
  note,
  guidance,
  busy,
  actionError,
  onNoteChange,
  onGuidanceChange,
  onSetMode,
  onApprove,
  onReject,
  onGuide,
  onEscalate,
  onClose,
}: {
  record: CaseApprovalRecord;
  canApprove: boolean;
  canGuide: boolean;
  mode: DetailMode;
  note: string;
  guidance: string;
  busy: boolean;
  actionError: string | null;
  onNoteChange: (value: string) => void;
  onGuidanceChange: (value: string) => void;
  onSetMode: (next: DetailMode) => void;
  onApprove: () => void;
  onReject: () => void;
  onGuide: () => void;
  onEscalate: () => void;
  onClose: () => void;
}) {
  const recommendation = smeRecommendation(record);
  const action = record.recommended_action;
  const eligibility = warrantyRefundEligibility(record);
  const isAwaiting = record.status === "awaiting_approval";
  const guidanceExhausted = record.guidance_round > 0;
  // AUTHORITY GATES: each control is ABSENT (not merely disabled) without the
  // capability, mirroring the backend route gates and the escalation UI. The
  // backend independently enforces the same tenant.actions.approve gate on
  // /reject — hiding the button here is a UX nicety, not the security
  // boundary.
  const showApprove = canApprove && isAwaiting;
  const showGuide = canGuide && isAwaiting && !guidanceExhausted;
  const showEscalate = canApprove && isAwaiting;
  // Reject is scoped to determinable warranty/refund verdicts only — a
  // cannot_determine case has no recommendation to act on yet (missing
  // evidence routes to escalate/probe, not a reject button). Cases without
  // any eligibility data (every other entry_category) keep escalate as
  // their only negative disposition, unchanged by this addition.
  const showReject =
    canApprove &&
    isAwaiting &&
    eligibility !== null &&
    eligibility.verdict !== "cannot_determine";

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
              Case approval review
            </p>
            <h3 className="truncate text-[15px] font-semibold text-ink-primary">
              {categoryTitle(record.entry_category)}
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

          {/* 1 — The customer's problem, stated before the proposed answer. */}
          <Section title="Customer issue">
            <Row label="Type" value={categoryTitle(record.entry_category)} />
            <Row label="Issue" value={record.issue_summary ?? "—"} />
            {record.product && <Row label="Product" value={record.product} />}
            {record.ticket_ref && <Row label="Ticket" value={record.ticket_ref} mono />}
            <Row label="Received" value={formatDate(record.requested_at)} />
          </Section>

          {/* 2 — What the AI recommends, with confidence and risk made legible. */}
          <Section title="AI recommendation">
            {recommendation ? (
              <>
                <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-ink-primary">
                  {recommendation.recommended_reply || "—"}
                </p>
                {recommendation.rationale && (
                  <p className="mt-2 rounded-md border border-border-subtle bg-surface px-3 py-2 text-[12px] text-ink-secondary">
                    {recommendation.rationale}
                  </p>
                )}
                <div className="mt-3">
                  <ConfidenceBar value={recommendation.confidence} />
                </div>
                <div className="mt-3">
                  <RiskLevel flags={recommendation.risk_flags} />
                </div>
              </>
            ) : (
              <p className="text-[13px] text-ink-secondary">
                SME review is still in progress for this case.
              </p>
            )}
          </Section>

          {/* 3 — Evidence the recommendation is grounded in. */}
          {recommendation && recommendation.citations.length > 0 && (
            <Section title="Evidence">
              <div className="flex flex-wrap gap-1.5">
                {recommendation.citations.map((citation, index) => (
                  <span
                    key={`${citation}-${index}`}
                    className="inline-flex items-center gap-1.5 rounded border border-border-subtle bg-surface px-2 py-1 text-[11.5px] text-ink-secondary"
                  >
                    <FileText className="h-3 w-3 text-ink-tertiary" strokeWidth={1.8} />
                    {citation}
                  </span>
                ))}
              </div>
            </Section>
          )}

          {/* Warranty/refund eligibility — the grounded W1-W3 determination,
              rendered as a readable evidence trail, never raw JSON. Shown
              whenever present, regardless of entry_category: a
              cannot_determine verdict can ride on a case that landed in a
              DIFFERENT category (e.g. "Resolution — approval required") via
              the existing fail-closed gate, and the missing-evidence detail
              still belongs in front of the reviewer there too. */}
          {eligibility && (
            <Section title="Warranty / refund eligibility">
              <div className="flex flex-wrap items-center gap-2">
                <VerdictBadge verdict={eligibility.verdict} />
                <span className="font-technical text-[11px] text-ink-tertiary">
                  {humanize(eligibility.claimType)}
                </span>
              </div>

              {eligibility.verdict === "cannot_determine" && (
                <p className="rounded-md border border-warning-amber/30 bg-surface px-3 py-2 text-[12.5px] leading-relaxed text-ink-primary">
                  The eligibility determination could not reach a verdict —
                  required evidence was missing, low-confidence, or
                  unparseable.{" "}
                  {eligibility.missingEvidence.length > 0 && (
                    <>
                      Missing:{" "}
                      <span className="font-technical">
                        {eligibility.missingEvidence.map(humanize).join(", ")}
                      </span>
                      .
                    </>
                  )}
                </p>
              )}

              {eligibility.grounding.length > 0 && (
                <div className="space-y-2">
                  {eligibility.grounding.map((check) => (
                    <GroundingCheckRow key={check.name} check={check} />
                  ))}
                </div>
              )}

              {eligibility.verdict === "eligible" && (
                <div className="flex flex-wrap items-center gap-2 rounded-md border border-border-subtle bg-surface px-3 py-2">
                  <span className="font-technical text-[10px] uppercase tracking-[0.12em] text-ink-tertiary">
                    Recommended remedy
                  </span>
                  <span className="text-[13px] font-medium text-ink-primary">
                    {eligibility.recommendedRemedy
                      ? humanize(eligibility.recommendedRemedy)
                      : "None configured for this claim type"}
                  </span>
                  {eligibility.recommendedRemedy && (
                    <AvailabilityBadge availability={eligibility.recommendedRemedyAvailability} />
                  )}
                </div>
              )}

              {eligibility.verdict === "ineligible" && (
                <p className="rounded-md border border-red-alert/25 bg-surface px-3 py-2 text-[12.5px] leading-relaxed text-ink-primary">
                  Denied based on the grounded checks above — review the
                  failed check(s) before deciding.
                </p>
              )}
            </Section>
          )}

          {action && (
            <Section title="Bound action (fires on approve)">
              <Row label="Tool" value={String(action.tool_name ?? "—")} mono />
              <p className="pt-1 font-technical text-[11px] text-ink-tertiary">
                Approving this case releases the governed action grant through the
                existing action-approval path.
              </p>
              <TechnicalDetails label="Show action identifier" openLabel="Hide action identifier">
                <Row
                  label="Action approval"
                  value={String(action.action_approval_id ?? "—")}
                  mono
                />
              </TechnicalDetails>
            </Section>
          )}

          {/* 4 — Governance & lifecycle; raw identifiers kept behind a toggle. */}
          <Section title="Governance & lifecycle">
            <Row label="Status" value={statusLabel(record.status)} />
            <Row label="Guidance round" value={`${record.guidance_round} / 1`} />
            {record.resolved_by && <Row label="Resolved by" value={record.resolved_by} />}
            {record.resolved_at && (
              <Row label="Resolved at" value={formatDate(record.resolved_at)} />
            )}
            <TechnicalDetails label="Show case identifiers" openLabel="Hide case identifiers">
              <div className="space-y-2">
                <Row label="Case ID" value={record.approval_case_id} mono />
                <Row
                  label="Session"
                  value={record.session_id ?? "—"}
                  mono={Boolean(record.session_id)}
                />
                <Row
                  label="Resolution proposal"
                  value={record.resolution_proposal_id ?? "—"}
                  mono={Boolean(record.resolution_proposal_id)}
                />
                <Row
                  label="Governance decision"
                  value={record.governance_decision_id ?? "—"}
                  mono={Boolean(record.governance_decision_id)}
                />
              </div>
            </TechnicalDetails>
          </Section>

          {/* ---- Controls: each gated + ABSENT without the capability ---- */}
          {mode === "review" &&
            (showApprove || showReject || showGuide || showEscalate) && (
            <div className="flex flex-col gap-2">
              {showApprove && (
                <button
                  type="button"
                  onClick={() => onSetMode("approve")}
                  disabled={busy}
                  className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-green-success px-4 text-[13px] font-semibold uppercase tracking-[0.08em] text-white disabled:opacity-60"
                >
                  <Check className="h-4 w-4" strokeWidth={1.8} />
                  Approve recommendation
                </button>
              )}
              {showReject && (
                <button
                  type="button"
                  onClick={() => onSetMode("reject")}
                  disabled={busy}
                  className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-red-alert bg-surface px-4 text-[13px] font-semibold uppercase tracking-[0.08em] text-red-alert transition-colors hover:bg-surface-raised disabled:opacity-50"
                >
                  <Ban className="h-4 w-4" strokeWidth={1.8} />
                  Reject recommendation
                </button>
              )}
              {showGuide && (
                <button
                  type="button"
                  onClick={() => onSetMode("guide")}
                  disabled={busy}
                  className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-gold-primary bg-surface px-4 text-[13px] font-semibold uppercase tracking-[0.08em] text-gold-primary transition-colors hover:bg-surface-raised disabled:opacity-50"
                >
                  <MessageSquarePlus className="h-4 w-4" strokeWidth={1.8} />
                  Guide a re-proposal
                </button>
              )}
              {showEscalate && (
                <button
                  type="button"
                  onClick={() => onSetMode("escalate")}
                  disabled={busy}
                  className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-red-alert bg-surface px-4 text-[13px] font-semibold uppercase tracking-[0.08em] text-red-alert transition-colors hover:bg-surface-raised disabled:opacity-50"
                >
                  <X className="h-4 w-4" strokeWidth={1.8} />
                  Escalate to escalation queue
                </button>
              )}
            </div>
          )}

          {/* Approve confirm — deliberate, names exactly what proceeds. */}
          {mode === "approve" && showApprove && (
            <div className="rounded-lg border border-green-success/40 bg-surface-raised p-4">
              <div className="flex items-center gap-2 text-green-success">
                <ShieldCheck className="h-4 w-4" strokeWidth={1.9} />
                <span className="font-technical text-[11px] font-semibold uppercase tracking-[0.12em]">
                  Confirm approval
                </span>
              </div>
              <p className="mt-2 text-[13px] leading-relaxed text-ink-primary">
                You are letting this SME-recommended resolution{" "}
                <strong>proceed</strong>
                {action ? " and releasing its bound action" : ""}. The customer-
                facing reply that will proceed is:
              </p>
              <p className="mt-2 rounded-md border border-border-subtle bg-surface px-3 py-2 text-[12px] text-ink-secondary">
                {recommendation?.recommended_reply || record.issue_summary || "—"}
              </p>
              <label
                htmlFor="case-approve-note"
                className="mt-3 block font-technical text-[10px] uppercase tracking-[0.14em] text-ink-tertiary"
              >
                Approval note (optional)
              </label>
              <textarea
                id="case-approve-note"
                value={note}
                onChange={(event) => onNoteChange(event.target.value)}
                placeholder="Why this approval is justified…"
                className="mt-2 min-h-[72px] w-full resize-y rounded-md border border-border-subtle bg-surface px-3 py-2 text-[13px] text-ink-primary outline-none transition-colors focus:border-gold-primary"
              />
              <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                <button
                  type="button"
                  onClick={onApprove}
                  disabled={busy}
                  className="inline-flex h-10 flex-1 items-center justify-center gap-2 rounded-md bg-green-success px-4 text-[13px] font-semibold uppercase tracking-[0.08em] text-white disabled:opacity-60"
                >
                  <Check className="h-4 w-4" strokeWidth={1.8} />
                  Confirm approve
                </button>
                <button
                  type="button"
                  onClick={() => onSetMode("review")}
                  disabled={busy}
                  className="inline-flex h-10 items-center justify-center rounded-md border border-border-subtle bg-surface px-4 text-[13px] font-semibold uppercase tracking-[0.08em] text-ink-secondary hover:text-ink-primary disabled:opacity-50"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {/* Reject confirm — a terminal "no", distinct from escalate: no
              connector fires, no customer reply is delivered, and any bound
              action is explicitly denied so it cannot fire through another
              path later. */}
          {mode === "reject" && showReject && (
            <div className="rounded-lg border border-red-alert/40 bg-surface-raised p-4">
              <div className="flex items-center gap-2 text-red-alert">
                <Ban className="h-4 w-4" strokeWidth={1.9} />
                <span className="font-technical text-[11px] font-semibold uppercase tracking-[0.12em]">
                  Confirm rejection
                </span>
              </div>
              <p className="mt-2 text-[13px] leading-relaxed text-ink-primary">
                You are <strong>denying</strong> this recommendation. No
                connector fires and the customer-facing reply above is{" "}
                <strong>not</strong> delivered
                {action ? " — its bound action is denied too" : ""}.
              </p>
              <label
                htmlFor="case-reject-note"
                className="mt-3 block font-technical text-[10px] uppercase tracking-[0.14em] text-ink-tertiary"
              >
                Rejection reason (optional)
              </label>
              <textarea
                id="case-reject-note"
                value={note}
                onChange={(event) => onNoteChange(event.target.value)}
                placeholder="Why this recommendation is being denied…"
                className="mt-2 min-h-[72px] w-full resize-y rounded-md border border-border-subtle bg-surface px-3 py-2 text-[13px] text-ink-primary outline-none transition-colors focus:border-red-alert"
              />
              <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                <button
                  type="button"
                  onClick={onReject}
                  disabled={busy}
                  className="inline-flex h-10 flex-1 items-center justify-center gap-2 rounded-md border border-red-alert bg-surface px-4 text-[13px] font-semibold uppercase tracking-[0.08em] text-red-alert transition-colors hover:bg-red-alert/10 disabled:opacity-50"
                >
                  <Ban className="h-4 w-4" strokeWidth={1.8} />
                  Confirm reject
                </button>
                <button
                  type="button"
                  onClick={() => onSetMode("review")}
                  disabled={busy}
                  className="inline-flex h-10 items-center justify-center rounded-md border border-border-subtle bg-surface px-4 text-[13px] font-semibold uppercase tracking-[0.08em] text-ink-secondary hover:text-ink-primary disabled:opacity-50"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {/* Escalate — the "or escalate" exit; hands the case to the escalation queue. */}
          {mode === "escalate" && showEscalate && (
            <div className="rounded-lg border border-red-alert/40 bg-surface-raised p-4">
              <div className="flex items-center gap-2 text-red-alert">
                <X className="h-4 w-4" strokeWidth={1.9} />
                <span className="font-technical text-[11px] font-semibold uppercase tracking-[0.12em]">
                  Escalate this case
                </span>
              </div>
              <p className="mt-2 text-[13px] leading-relaxed text-ink-primary">
                This hands the case to the <strong>escalation queue</strong> for
                human handling instead of approving the recommendation.
              </p>
              <label
                htmlFor="case-escalate-reason"
                className="mt-3 block font-technical text-[10px] uppercase tracking-[0.14em] text-ink-tertiary"
              >
                Escalation reason (required)
              </label>
              <textarea
                id="case-escalate-reason"
                value={note}
                onChange={(event) => onNoteChange(event.target.value)}
                className="mt-2 min-h-[72px] w-full resize-y rounded-md border border-border-subtle bg-surface px-3 py-2 text-[13px] text-ink-primary outline-none transition-colors focus:border-red-alert"
              />
              <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                <button
                  type="button"
                  onClick={onEscalate}
                  disabled={busy || !note.trim()}
                  className="inline-flex h-10 flex-1 items-center justify-center gap-2 rounded-md border border-red-alert bg-surface px-4 text-[13px] font-semibold uppercase tracking-[0.08em] text-red-alert transition-colors hover:bg-surface-raised disabled:opacity-50"
                >
                  <X className="h-4 w-4" strokeWidth={1.8} />
                  Confirm escalate
                </button>
                <button
                  type="button"
                  onClick={() => onSetMode("review")}
                  disabled={busy}
                  className="inline-flex h-10 items-center justify-center rounded-md border border-border-subtle bg-surface px-4 text-[13px] font-semibold uppercase tracking-[0.08em] text-ink-secondary hover:text-ink-primary disabled:opacity-50"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {/* Guide — submits a prompt; re-runs the agent UNDER governance. */}
          {mode === "guide" && showGuide && (
            <div className="rounded-lg border border-gold-primary/50 bg-surface-raised p-4">
              <div className="flex items-center gap-2 text-gold-primary">
                <MessageSquarePlus className="h-4 w-4" strokeWidth={1.9} />
                <span className="font-technical text-[11px] font-semibold uppercase tracking-[0.12em]">
                  Guide the agent (one bounded re-proposal)
                </span>
              </div>
              <p className="mt-2 text-[13px] leading-relaxed text-ink-primary">
                Your guidance steers a single re-proposal. It is{" "}
                <strong>not a direct override</strong>: the re-proposed resolution
                still re-runs the full resolution governance gate, so guidance
                cannot force an ungrounded reply. After this, the case returns for
                a final approve or escalate.
              </p>
              <label
                htmlFor="case-guidance"
                className="mt-3 block font-technical text-[10px] uppercase tracking-[0.14em] text-ink-tertiary"
              >
                Guidance prompt (required)
              </label>
              <textarea
                id="case-guidance"
                value={guidance}
                onChange={(event) => onGuidanceChange(event.target.value)}
                placeholder="e.g. Ask for the order number and cite the 2-year warranty window…"
                className="mt-2 min-h-[88px] w-full resize-y rounded-md border border-border-subtle bg-surface px-3 py-2 text-[13px] text-ink-primary outline-none transition-colors focus:border-gold-primary"
              />
              <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                <button
                  type="button"
                  onClick={onGuide}
                  disabled={busy || !guidance.trim()}
                  className="inline-flex h-10 flex-1 items-center justify-center gap-2 rounded-md bg-gold-primary px-4 text-[13px] font-semibold uppercase tracking-[0.08em] text-white disabled:opacity-60"
                >
                  <Sparkles className="h-4 w-4" strokeWidth={1.8} />
                  Submit guidance
                </button>
                <button
                  type="button"
                  onClick={() => onSetMode("review")}
                  disabled={busy}
                  className="inline-flex h-10 items-center justify-center rounded-md border border-border-subtle bg-surface px-4 text-[13px] font-semibold uppercase tracking-[0.08em] text-ink-secondary hover:text-ink-primary disabled:opacity-50"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {guidanceExhausted && isAwaiting && (
            <div className="flex items-center gap-2 rounded-md border border-border-subtle bg-surface-raised px-3 py-2 text-[12px] leading-relaxed text-ink-secondary">
              <BadgeCheck className="h-3.5 w-3.5 text-gold-primary" strokeWidth={1.8} />
              Guidance has been used (1 / 1). The next step is a final approve or
              escalate.
            </div>
          )}

          {!canApprove && !canGuide && (
            <div className="flex items-center gap-2 rounded-md border border-border-subtle bg-surface-raised px-3 py-2 font-technical text-[11px] text-ink-tertiary">
              <Lock className="h-3.5 w-3.5" strokeWidth={1.8} />
              Acting on this case requires the tenant.actions.approve (approve) or
              tenant.resolution.guide (guide) capability.
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(100, Math.round((value ?? 0) * 100)));
  const fill =
    pct >= 85 ? "bg-green-success" : pct >= 60 ? "bg-warning-amber" : "bg-red-alert";
  const text =
    pct >= 85
      ? "text-green-success"
      : pct >= 60
        ? "text-warning-amber"
        : "text-red-alert";
  return (
    <div>
      <div className="flex items-center justify-between">
        <span className="font-technical text-[10px] uppercase tracking-[0.12em] text-ink-tertiary">
          AI confidence
        </span>
        <span className={cn("font-technical text-[12px] font-semibold tabular-nums", text)}>
          {pct}%
        </span>
      </div>
      <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-surface-sunken">
        <div className={cn("h-full rounded-full", fill)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function RiskLevel({ flags }: { flags: string[] }) {
  if (flags.length === 0) {
    return (
      <div className="flex items-center gap-2 text-[12px] text-green-success">
        <ShieldCheck className="h-3.5 w-3.5" strokeWidth={1.8} />
        No risk flags raised
      </div>
    );
  }
  return (
    <div>
      <span className="font-technical text-[10px] uppercase tracking-[0.12em] text-ink-tertiary">
        Risk flags
      </span>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {flags.map((flag) => (
          <span
            key={flag}
            className="rounded border border-red-alert/40 bg-red-alert/10 px-2 py-0.5 font-technical text-[10px] uppercase tracking-[0.10em] text-red-alert"
          >
            {flag.replace(/_/g, " ")}
          </span>
        ))}
      </div>
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

function StatusBadge({ status }: { status: CaseApprovalStatus }) {
  const tone =
    status === "approved"
      ? "border-green-success/40 text-green-success"
      : status === "rejected" || status === "escalated"
        ? "border-red-alert/40 text-red-alert"
        : status === "awaiting_approval"
          ? "border-gold-primary/40 text-gold-primary"
          : "border-border-subtle text-ink-secondary";
  return (
    <span
      className={cn(
        "shrink-0 rounded border bg-surface-raised px-2 py-1 font-technical text-[10px] uppercase tracking-[0.10em]",
        tone
      )}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}

type ParsedRecommendation = {
  recommended_reply: string;
  rationale: string;
  confidence: number;
  risk_flags: string[];
  citations: string[];
};

function smeRecommendation(record: CaseApprovalRecord): ParsedRecommendation | null {
  const raw = record.metadata?.["sme_recommendation"];
  if (!raw || typeof raw !== "object") return null;
  const value = raw as Record<string, unknown>;
  const flags = value["risk_flags"];
  return {
    recommended_reply:
      typeof value["recommended_reply"] === "string" ? value["recommended_reply"] : "",
    rationale: typeof value["rationale"] === "string" ? value["rationale"] : "",
    confidence: typeof value["confidence"] === "number" ? value["confidence"] : 0,
    risk_flags: Array.isArray(flags)
      ? flags.filter((flag): flag is string => typeof flag === "string")
      : [],
    citations: parseCitations(value["citations"]),
  };
}

/** Render citations as human-readable source labels rather than raw objects. */
function parseCitations(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((entry, index) => {
    if (typeof entry === "string") return entry;
    if (entry && typeof entry === "object") {
      const obj = entry as Record<string, unknown>;
      for (const key of ["title", "source", "document_title", "document_id", "uri", "url"]) {
        if (typeof obj[key] === "string" && obj[key]) return obj[key] as string;
      }
    }
    return `Source ${index + 1}`;
  });
}

type EligibilityVerdict = "eligible" | "ineligible" | "cannot_determine";
type RemedyAvailability = "available" | "unconfirmed" | "not_applicable";

type GroundingCheck = {
  name: string;
  passed: boolean;
  rule: string;
  evidenceField: string;
  evidenceValue: string;
  evidenceConfidence: string;
  evidenceSource: string;
};

type WarrantyRefundEligibility = {
  claimType: string;
  verdict: EligibilityVerdict;
  recommendedRemedy: string | null;
  recommendedRemedyAvailability: RemedyAvailability | null;
  missingEvidence: string[];
  grounding: GroundingCheck[];
};

/**
 * Parses the W1-W3 eligibility determination embedded in
 * recommended_action.warranty_refund_eligibility. Defensive like
 * smeRecommendation: absent or malformed data renders nothing rather than
 * guessing — this is a recommendation a human verifies, never a value the
 * UI should fabricate.
 *
 * Each grounding check also carries evidence_source ("text" | "document" |
 * "none") — a trust signal for the reviewer (document-sourced evidence is
 * stronger than typed text). Rendered only when it names an actual source;
 * "none" or an absent/unrecognized value renders no source clause at all,
 * never a fabricated "document".
 */
function warrantyRefundEligibility(
  record: CaseApprovalRecord
): WarrantyRefundEligibility | null {
  const action = record.recommended_action;
  if (!action || typeof action !== "object") return null;
  const raw = (action as Record<string, unknown>)["warranty_refund_eligibility"];
  if (!raw || typeof raw !== "object") return null;
  const value = raw as Record<string, unknown>;

  const verdict = value["verdict"];
  if (verdict !== "eligible" && verdict !== "ineligible" && verdict !== "cannot_determine") {
    return null;
  }
  const availability = value["recommended_remedy_availability"];

  return {
    claimType: typeof value["claim_type"] === "string" ? value["claim_type"] : "—",
    verdict,
    recommendedRemedy:
      typeof value["recommended_remedy"] === "string" ? value["recommended_remedy"] : null,
    recommendedRemedyAvailability:
      availability === "available" || availability === "unconfirmed" || availability === "not_applicable"
        ? availability
        : null,
    missingEvidence: Array.isArray(value["missing_evidence"])
      ? value["missing_evidence"].filter((entry): entry is string => typeof entry === "string")
      : [],
    grounding: parseGrounding(value["grounding"]),
  };
}

function parseGrounding(raw: unknown): GroundingCheck[] {
  if (!Array.isArray(raw)) return [];
  const checks: GroundingCheck[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== "object") continue;
    const value = entry as Record<string, unknown>;
    if (typeof value["name"] !== "string" || typeof value["passed"] !== "boolean") continue;
    checks.push({
      name: value["name"],
      passed: value["passed"],
      rule: typeof value["rule"] === "string" ? value["rule"] : "—",
      evidenceField: typeof value["evidence_field"] === "string" ? value["evidence_field"] : "—",
      evidenceValue: typeof value["evidence_value"] === "string" ? value["evidence_value"] : "—",
      evidenceConfidence:
        typeof value["evidence_confidence"] === "string" ? value["evidence_confidence"] : "—",
      evidenceSource:
        typeof value["evidence_source"] === "string" ? value["evidence_source"] : "none",
    });
  }
  return checks;
}

/** snake_case -> "Snake case", for claim types, remedy names, and field names. */
function humanize(value: string): string {
  const spaced = value.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/**
 * Readable label for an evidence_source value. "none" and anything not
 * recognized return "" so the caller renders no source clause at all —
 * never a fabricated "from document" for evidence that has no real
 * source.
 */
function sourceLabel(source: string): string {
  if (source === "document") return "from document";
  if (source === "text") return "from message text";
  return "";
}

function VerdictBadge({ verdict }: { verdict: EligibilityVerdict }) {
  const tone =
    verdict === "eligible"
      ? "border-green-success/40 bg-green-success/10 text-green-success"
      : verdict === "ineligible"
        ? "border-red-alert/40 bg-red-alert/10 text-red-alert"
        : "border-warning-amber/40 bg-warning-amber/10 text-warning-amber";
  const Icon = verdict === "eligible" ? Check : verdict === "ineligible" ? XCircle : CircleHelp;
  const label = verdict === "cannot_determine" ? "Cannot determine" : humanize(verdict);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-technical text-[10.5px] font-semibold uppercase tracking-[0.10em]",
        tone
      )}
    >
      <Icon className="h-3 w-3" strokeWidth={2} />
      {label}
    </span>
  );
}

function AvailabilityBadge({ availability }: { availability: RemedyAvailability | null }) {
  if (!availability || availability === "not_applicable") return null;
  const tone =
    availability === "available"
      ? "border-green-success/40 text-green-success"
      : "border-warning-amber/40 text-warning-amber";
  const label = availability === "available" ? "Available" : "Availability unconfirmed";
  return (
    <span
      className={cn(
        "rounded border px-2 py-0.5 font-technical text-[10px] uppercase tracking-[0.10em]",
        tone
      )}
    >
      {label}
    </span>
  );
}

function GroundingCheckRow({ check }: { check: GroundingCheck }) {
  return (
    <div
      className={cn(
        "rounded-md border px-3 py-2",
        check.passed ? "border-border-subtle bg-surface" : "border-red-alert/25 bg-surface"
      )}
    >
      <div className="flex items-start gap-2">
        {check.passed ? (
          <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-green-success" strokeWidth={2} />
        ) : (
          <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-alert" strokeWidth={2} />
        )}
        <div className="min-w-0">
          <p className="text-[13px] font-medium text-ink-primary">{humanize(check.name)}</p>
          <p className="mt-0.5 text-[12px] leading-relaxed text-ink-secondary">
            {humanize(check.evidenceField)}: <span className="text-ink-primary">{check.evidenceValue}</span>
            {" · "}
            {check.evidenceConfidence} confidence
            {sourceLabel(check.evidenceSource) && ` · ${sourceLabel(check.evidenceSource)}`}
          </p>
          <p className="mt-0.5 font-technical text-[10.5px] text-ink-tertiary">
            rule: {check.rule}
          </p>
        </div>
      </div>
    </div>
  );
}

function statusLabel(status: CaseApprovalStatus): string {
  return status.replace(/_/g, " ").replace(/\bsme\b/i, "SME");
}

function categoryTitle(category: CaseApprovalRecord["entry_category"]): string {
  switch (category) {
    case "resolution_require_approval":
      return "Resolution — approval required";
    case "resolution_needs_human_approval":
      return "Resolution — needs human approval";
    case "refund_warranty":
      return "Refund / warranty";
    case "low_confidence":
      return "Low-confidence resolution";
    case "coordination_human_review":
      return "Coordination — human review";
    case "crisis_action":
      return "Crisis action";
    default:
      return category;
  }
}

function shortId(value: string): string {
  return value.length > 10 ? `${value.slice(0, 8)}…` : value;
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}
