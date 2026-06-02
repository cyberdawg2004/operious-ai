"use client";

import type { ReactNode } from "react";
import { useCallback, useMemo, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Copy,
  FileJson,
  GitBranch,
  Search,
  X,
} from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-state";
import {
  apiRequest,
  listSupervisorInspections,
  type QAScoreRecord,
} from "@/lib/api";
import { useApiResource } from "@/lib/use-api-resource";
import { cn } from "@/lib/utils";

export type TraceLookup = {
  value: string;
  mode?: "session_id" | "event_id" | "root_event_id" | "governance_decision_id";
};

type SessionTimelineEvent = {
  timeline_event_id: string;
  session_id: string;
  dispatch_id: string | null;
  tenant_id: string | null;
  event_type: string;
  timestamp: string;
  payload: Record<string, unknown>;
  created_at: string;
};

type SessionTimelineResponse = {
  events: SessionTimelineEvent[];
  total: number;
};

type SessionEventRecord = {
  event_id: string;
  session_id: string;
  sequence: number;
  kind: string;
  continuity_mode: string;
  occurred_at: string;
  recorded_at: string;
  payload: Record<string, unknown>;
  correlation_id: string | null;
  annotation: string | null;
  governance_decision_id: string | null;
  governance_chain_id: string | null;
  metadata: Record<string, unknown>;
};

type SessionEventsResponse = {
  items: SessionEventRecord[];
  total: number;
};

type SessionTraceResponse = {
  timeline: SessionTimelineResponse;
  sessionEvents: SessionEventsResponse;
};

type TimelineEventView = SessionTimelineEvent & {
  sequence: number | null;
  correlation_id: string | null;
  continuity_mode: string | null;
  governance_decision_id: string | null;
  governance_chain_id: string | null;
  recorded_at: string | null;
  metadata: Record<string, unknown>;
};

interface RetrievedCitation {
  rank: number;
  document_id: string;
  title: string;
  document_type: string;
  document_status: string;
  score: number;
  chunk_ordinal: number;
  char_start?: number;
  char_end?: number;
  token_count: number;
  citation_schema_version?: number;
  chunk_id?: string;
  vector_id?: string;
  document_version?: number;
  vector_index_name?: string;
  safe_excerpt?: string;
  safe_excerpt_sha256?: string;
  chunk_content_hash?: string;
}

interface RecommendedResolutionAction {
  type: string;
  label: string;
  requires_execution: boolean;
}

interface ResolutionProposalPayload {
  proposed_customer_reply: string;
  resolution_category: string;
  confidence: number;
  autonomy_decision: string;
  status: string;
  supervisor_verdict: string;
  governance_verdict: string;
  recommended_actions: RecommendedResolutionAction[];
  evidence: RetrievedCitation[];
}

interface ResolutionOutboundDraftPayload {
  draft_id: string;
  proposal_id: string;
  governance_decision_id: string | null;
  status: string;
  draft_body: string;
  draft_body_sha256: string;
  resolution_category: string;
  confidence: number;
  send_eligible: boolean;
}

type TraceInspectorProps = {
  initialTraceId?: string | null;
  initialLookup?: TraceLookup | null;
};

const emptyTrace: SessionTraceResponse = {
  timeline: { events: [], total: 0 },
  sessionEvents: { items: [], total: 0 },
};

export function TraceInspector({ initialTraceId, initialLookup }: TraceInspectorProps) {
  const initialSessionId = initialLookup?.value ?? initialTraceId ?? "";
  const [searchValue, setSearchValue] = useState(initialSessionId);
  const [loadedSessionId, setLoadedSessionId] = useState<string | null>(
    initialSessionId.trim() || null
  );
  const [expandedPayloads, setExpandedPayloads] = useState<Set<string>>(new Set());
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [showRawJson, setShowRawJson] = useState(false);
  const [copyStatus, setCopyStatus] = useState<string | null>(null);

  const loadTrace = useCallback(async (): Promise<SessionTraceResponse> => {
    if (!loadedSessionId) return emptyTrace;
    const encodedSessionId = encodeURIComponent(loadedSessionId);
    const [timeline, sessionEvents] = await Promise.all([
      apiRequest<SessionTimelineResponse>(`/session/${encodedSessionId}/timeline`),
      apiRequest<SessionEventsResponse>(`/session/sessions/${encodedSessionId}/events`),
    ]);
    return { timeline, sessionEvents };
  }, [loadedSessionId]);
  const loadQAScore = useCallback(async (): Promise<QAScoreRecord | null> => {
    if (!loadedSessionId) return null;
    const page = await listSupervisorInspections({
      status: "all",
      session_id: loadedSessionId,
      limit: 1,
      offset: 0,
    });
    return page.items[0]?.qa_score ?? null;
  }, [loadedSessionId]);

  const { data, error, isLoading, reload } = useApiResource(loadTrace);
  const { data: qaScore } = useApiResource(loadQAScore);
  const trace = data ?? emptyTrace;
  const events = useMemo(() => mergeTimelineEvents(trace), [trace]);
  const selectedEvent = useMemo(
    () =>
      events.find((event) => event.timeline_event_id === selectedEventId) ??
      events[0] ??
      null,
    [events, selectedEventId]
  );
  const selectedResolutionProposal = useMemo(
    () => (selectedEvent ? resolutionProposalForEvent(selectedEvent) : null),
    [selectedEvent]
  );
  const selectedResolutionDraft = useMemo(
    () => (selectedEvent ? resolutionDraftForEvent(selectedEvent) : null),
    [selectedEvent]
  );
  const metadata = useMemo(
    () => deriveTraceMetadata(loadedSessionId, events),
    [events, loadedSessionId]
  );

  const handleOpenTrace = () => {
    const normalized = searchValue.trim();
    setLoadedSessionId(normalized || null);
    setSelectedEventId(null);
    setExpandedPayloads(new Set());
    setCopyStatus(null);
    setShowRawJson(false);
  };

  const togglePayload = (eventId: string) => {
    setExpandedPayloads((current) => {
      const next = new Set(current);
      if (next.has(eventId)) {
        next.delete(eventId);
      } else {
        next.add(eventId);
      }
      return next;
    });
  };

  const copyText = async (value: string | null | undefined, label: string) => {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      setCopyStatus(`${label} copied`);
    } catch {
      setCopyStatus("Clipboard denied");
    }
  };

  return (
    <div className="min-w-0 flex-1 bg-canvas px-4 py-5 sm:px-6 lg:px-8">
      <div className="mb-6">
        <div className="mb-2 font-mono text-[11px] uppercase tracking-[0.18em] text-gold-primary">
          TRACE - SESSION TIMELINE
        </div>

        <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
          <h1 className="font-display text-[32px] font-bold text-ink-primary">
            Trace Inspector
          </h1>

          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <div className="relative min-w-0">
              <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-tertiary" />
              <input
                type="text"
                placeholder="Session ID..."
                value={searchValue}
                onChange={(event) => setSearchValue(event.target.value)}
                className="h-11 w-full rounded border border-border-subtle bg-surface-raised pl-9 pr-4 font-sans text-[13px] text-ink-primary outline-none transition-colors duration-160 placeholder:text-ink-tertiary focus:border-gold-primary sm:h-10 sm:w-[380px]"
                onKeyDown={(event) => event.key === "Enter" && handleOpenTrace()}
              />
            </div>
            <button
              type="button"
              onClick={handleOpenTrace}
              className="h-11 rounded bg-ink-primary px-4 font-sans text-[13px] font-medium text-white transition-opacity duration-160 hover:opacity-90 sm:h-10"
            >
              Open Trace
            </button>
            {loadedSessionId && (
              <button
                type="button"
                onClick={() => void copyText(loadedSessionId, "Session ID")}
                className="inline-flex h-11 items-center gap-2 rounded border border-border-subtle px-3 font-technical text-[10px] uppercase tracking-[0.12em] text-ink-secondary transition-colors hover:border-border-defined hover:text-ink-primary sm:h-10"
              >
                <Copy className="h-3.5 w-3.5" strokeWidth={1.5} />
                Copy Session ID
              </button>
            )}
          </div>
        </div>
      </div>

      {!loadedSessionId && !isLoading && (
        <EmptyState
          title="No session trace selected"
          message="Select a session from the Operations Queue or enter a session ID to load its tenant-scoped timeline."
        />
      )}

      {isLoading && <LoadingState label="Loading session timeline..." />}

      {error && !isLoading && (
        <ErrorState
          title="Session timeline unavailable"
          message={error}
          actionLabel="Retry"
          onAction={reload}
        />
      )}

      {loadedSessionId && !isLoading && !error && events.length === 0 && (
        <EmptyState
          title="No timeline events"
          message="The backend returned no timeline events for this session."
          actionLabel="Refresh trace"
          onAction={reload}
        />
      )}

      {loadedSessionId && events.length > 0 && !isLoading && !error && (
        <>
          <div className="mb-6 overflow-x-auto rounded-lg border border-border-subtle bg-surface-raised p-3">
            <div className="flex min-w-[900px] items-stretch">
              <MetadataField label="SESSION" value={shortId(loadedSessionId)} mono />
              <Divider />
              <MetadataField label="TENANT" value={metadata.tenantId} />
              <Divider />
              <MetadataField label="EVENTS" value={String(trace.timeline.total)} mono />
              <Divider />
              <MetadataField label="ENRICHED" value={String(trace.sessionEvents.total)} mono />
              <Divider />
              <MetadataField label="FIRST EVENT" value={metadata.firstEvent} mono />
              <Divider />
              <MetadataField label="DURATION" value={metadata.duration} mono />
              <Divider />
              <MetadataField
                label="RAW"
                value={
                  <button
                    type="button"
                    onClick={() => setShowRawJson(true)}
                    className="inline-flex h-8 items-center gap-2 rounded border border-border-subtle px-2 font-technical text-[10px] uppercase tracking-[0.12em] text-ink-secondary transition-colors hover:border-border-defined hover:text-ink-primary"
                  >
                    <FileJson className="h-3.5 w-3.5" strokeWidth={1.5} />
                    View Raw JSON
                  </button>
                }
              />
            </div>
          </div>

          {copyStatus && (
            <div className="mb-4 rounded border border-border-subtle bg-surface-raised px-3 py-2 font-mono text-[11px] uppercase tracking-[0.12em] text-ink-tertiary">
              {copyStatus}
            </div>
          )}

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(340px,0.9fr)]">
            <div className="min-w-0 rounded-lg border border-border-subtle bg-surface-raised p-4 sm:p-5">
              <div className="mb-5 font-mono text-[11px] uppercase tracking-[0.18em] text-ink-tertiary">
                Canonical Timeline
              </div>

              <div className="relative space-y-4 pl-7">
                <div className="absolute bottom-0 left-[13px] top-0 w-px bg-border-subtle" />
                {events.map((event) => {
                  const isExpanded = expandedPayloads.has(event.timeline_event_id);
                  const eventColor = colorForEventType(event.event_type);
                  const citations = citationsForEvent(event);
                  const resolutionProposal = resolutionProposalForEvent(event);
                  const resolutionDraft = resolutionDraftForEvent(event);

                  return (
                    <div key={event.timeline_event_id} className="relative">
                      <button
                        type="button"
                        onClick={() => setSelectedEventId(event.timeline_event_id)}
                        className={cn(
                          "absolute -left-[21px] top-3 h-3.5 w-3.5 rounded-full ring-4 ring-[var(--surface-raised)] transition-transform",
                          selectedEvent?.timeline_event_id === event.timeline_event_id && "scale-125"
                        )}
                        style={{ backgroundColor: eventColor }}
                        aria-label={`Select event ${event.event_type}`}
                      />

                      <div
                        className={cn(
                          "rounded border bg-surface p-4 transition-colors",
                          selectedEvent?.timeline_event_id === event.timeline_event_id
                            ? "border-gold-primary"
                            : "border-border-subtle"
                        )}
                      >
                        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                          <button
                            type="button"
                            onClick={() => setSelectedEventId(event.timeline_event_id)}
                            className="min-w-0 text-left"
                          >
                            <div className="font-mono text-[12px] uppercase tracking-[0.08em]" style={{ color: eventColor }}>
                              {formatEventLabel(event.event_type)}
                            </div>
                            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
                              <span
                                className="font-technical text-[11px] tabular-nums text-ink-secondary"
                                title={formatAbsoluteTime(event.timestamp)}
                              >
                                {formatRelativeTime(event.timestamp)}
                              </span>
                              {event.dispatch_id && (
                                <span className="font-technical text-[11px] tabular-nums text-ink-tertiary">
                                  dispatch {shortId(event.dispatch_id)}
                                </span>
                              )}
                              {event.sequence !== null && (
                                <span className="font-technical text-[11px] tabular-nums text-ink-tertiary">
                                  seq {event.sequence}
                                </span>
                              )}
                            </div>
                          </button>

                          <div className="flex shrink-0 flex-wrap gap-2">
                            {event.dispatch_id && (
                              <button
                                type="button"
                                onClick={() => void copyText(event.dispatch_id, "Dispatch ID")}
                                className="inline-flex h-9 items-center gap-2 rounded border border-border-subtle px-2 font-technical text-[10px] uppercase tracking-[0.12em] text-ink-secondary transition-colors hover:border-border-defined hover:text-ink-primary"
                              >
                                <Copy className="h-3.5 w-3.5" strokeWidth={1.5} />
                                Dispatch
                              </button>
                            )}
                            <button
                              type="button"
                              onClick={() => togglePayload(event.timeline_event_id)}
                              className="inline-flex h-9 items-center gap-2 rounded border border-border-subtle px-2 font-technical text-[10px] uppercase tracking-[0.12em] text-ink-secondary transition-colors hover:border-border-defined hover:text-ink-primary"
                            >
                              {isExpanded ? (
                                <ChevronDown className="h-3.5 w-3.5" strokeWidth={1.5} />
                              ) : (
                                <ChevronRight className="h-3.5 w-3.5" strokeWidth={1.5} />
                              )}
                              Payload
                            </button>
                          </div>
                        </div>

                        {event.correlation_id && (
                          <div className="mt-3 inline-flex items-center gap-2 rounded bg-surface-sunken px-2 py-1 font-technical text-[11px] text-ink-secondary">
                            <GitBranch className="h-3.5 w-3.5 text-ink-tertiary" strokeWidth={1.5} />
                            correlation {shortId(event.correlation_id)}
                          </div>
                        )}

                        {resolutionProposal && (
                          <ResolutionProposalSummary proposal={resolutionProposal} />
                        )}

                        {resolutionDraft && (
                          <ResolutionDraftSummary draft={resolutionDraft} />
                        )}

                        {citations.length > 0 && (
                          <KnowledgeSources citations={citations} />
                        )}

                        {isExpanded && (
                          <div className="mt-4 rounded border border-border-subtle bg-surface-sunken p-3">
                            <JsonTree value={event.payload} />
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="min-w-0 rounded-lg border border-border-subtle bg-surface-raised">
              <div className="flex items-center justify-between border-b border-border-subtle px-4 py-3 sm:px-5">
                <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-ink-tertiary">
                  Event Detail
                </span>
                {selectedEvent && (
                  <button
                    type="button"
                    onClick={() => void copyText(JSON.stringify(selectedEvent, null, 2), "Event JSON")}
                    className="flex h-11 w-11 items-center justify-center rounded transition-colors duration-160 hover:bg-[var(--surface-sunken)] sm:h-9 sm:w-9"
                    aria-label="Copy selected event JSON"
                  >
                    <Copy className="h-4 w-4 text-ink-tertiary" strokeWidth={1.5} />
                  </button>
                )}
              </div>

              {selectedEvent ? (
                <div className="space-y-5 p-4 sm:p-5">
                  <div>
                    <div
                      className="mb-1 font-mono text-[14px] uppercase tracking-wide"
                      style={{ color: colorForEventType(selectedEvent.event_type) }}
                    >
                      {formatEventLabel(selectedEvent.event_type)}
                    </div>
                    <p
                      className="font-mono text-[12px] text-ink-tertiary"
                      title={formatAbsoluteTime(selectedEvent.timestamp)}
                    >
                      {formatRelativeTime(selectedEvent.timestamp)} - {selectedEvent.timeline_event_id}
                    </p>
                  </div>

                  <div className="flex flex-wrap gap-3 rounded-lg bg-surface-sunken p-3">
                    <Metric icon={<Clock className="h-4 w-4" />} value={formatAbsoluteTime(selectedEvent.timestamp)} />
                    {selectedEvent.sequence !== null && (
                      <Metric icon={<CheckCircle2 className="h-4 w-4" />} value={`sequence ${selectedEvent.sequence}`} />
                    )}
                    {selectedEvent.correlation_id && (
                      <Metric icon={<GitBranch className="h-4 w-4" />} value={shortId(selectedEvent.correlation_id)} />
                    )}
                  </div>

                  {selectedResolutionProposal && (
                    <ResolutionProposalSummary proposal={selectedResolutionProposal} compact />
                  )}

                  {selectedResolutionDraft && (
                    <ResolutionDraftSummary draft={selectedResolutionDraft} compact />
                  )}

                  {qaScore && <TraceQAScore score={qaScore} />}

                  <div className="space-y-4">
                    <DetailRow label="TIMELINE EVENT ID" value={selectedEvent.timeline_event_id} />
                    <DetailRow label="SESSION ID" value={selectedEvent.session_id} />
                    {selectedEvent.dispatch_id && (
                      <DetailRow label="DISPATCH ID" value={selectedEvent.dispatch_id} />
                    )}
                    {selectedEvent.continuity_mode && (
                      <DetailRow label="CONTINUITY" value={selectedEvent.continuity_mode} />
                    )}
                    {selectedEvent.governance_decision_id && (
                      <DetailRow label="GOVERNANCE DECISION" value={selectedEvent.governance_decision_id} />
                    )}
                    {selectedEvent.governance_chain_id && (
                      <DetailRow label="GOVERNANCE CHAIN" value={selectedEvent.governance_chain_id} />
                    )}
                  </div>
                </div>
              ) : (
                <div className="flex h-[420px] items-center justify-center">
                  <p className="font-sans text-[14px] italic text-ink-tertiary">
                    Select an event to inspect
                  </p>
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {showRawJson && (
        <RawJsonModal
          response={trace.timeline}
          onClose={() => setShowRawJson(false)}
          onCopy={() =>
            void copyText(JSON.stringify(trace.timeline, null, 2), "Timeline response")
          }
        />
      )}
    </div>
  );
}

function mergeTimelineEvents(trace: SessionTraceResponse): TimelineEventView[] {
  const enrichedSessionIds = new Set(
    trace.sessionEvents.items.map((event) => event.session_id)
  );
  const eventDetails = new Map(
    trace.sessionEvents.items.map((event) => [event.event_id, event])
  );

  return trace.timeline.events
    .filter((event) => enrichedSessionIds.size === 0 || enrichedSessionIds.has(event.session_id))
    .map((event) => {
      const details = eventDetails.get(event.timeline_event_id);
      return {
        ...event,
        sequence: details?.sequence ?? null,
        correlation_id: details?.correlation_id ?? null,
        continuity_mode: details?.continuity_mode ?? null,
        governance_decision_id: details?.governance_decision_id ?? null,
        governance_chain_id: details?.governance_chain_id ?? null,
        recorded_at: details?.recorded_at ?? null,
        metadata: details?.metadata ?? {},
      };
    })
    .sort((left, right) => new Date(left.timestamp).getTime() - new Date(right.timestamp).getTime());
}

function citationsForEvent(event: TimelineEventView): RetrievedCitation[] {
  const citations =
    event.event_type === "resolution_proposal_created"
      ? event.payload.evidence
      : event.payload.retrieved_citations;
  if (!Array.isArray(citations)) return [];
  return citations.filter(isRetrievedCitation);
}

function resolutionProposalForEvent(
  event: TimelineEventView
): ResolutionProposalPayload | null {
  if (event.event_type !== "resolution_proposal_created") return null;
  const payload = event.payload;
  const proposedReply = stringField(payload.proposed_customer_reply);
  if (!proposedReply) return null;
  const actions = Array.isArray(payload.recommended_actions)
    ? payload.recommended_actions.filter(isRecommendedResolutionAction)
    : [];
  const evidence = Array.isArray(payload.evidence)
    ? payload.evidence.filter(isRetrievedCitation)
    : [];

  return {
    proposed_customer_reply: proposedReply,
    resolution_category: stringField(payload.resolution_category) || "unknown",
    confidence: numberField(payload.confidence),
    autonomy_decision: stringField(payload.autonomy_decision) || "unknown",
    status: stringField(payload.status) || "unknown",
    supervisor_verdict: stringField(payload.supervisor_verdict) || "unknown",
    governance_verdict: stringField(payload.governance_verdict) || "unknown",
    recommended_actions: actions,
    evidence,
  };
}

function resolutionDraftForEvent(
  event: TimelineEventView
): ResolutionOutboundDraftPayload | null {
  if (event.event_type !== "resolution_outbound_draft_created") return null;
  const payload = event.payload;
  const draftBody = stringField(payload.draft_body);
  if (!draftBody) return null;

  return {
    draft_id: stringField(payload.draft_id) || "unknown",
    proposal_id: stringField(payload.proposal_id) || "unknown",
    governance_decision_id: stringField(payload.governance_decision_id),
    status: stringField(payload.status) || "unknown",
    draft_body: draftBody,
    draft_body_sha256: stringField(payload.draft_body_sha256) || "unknown",
    resolution_category: stringField(payload.resolution_category) || "unknown",
    confidence: numberField(payload.confidence),
    send_eligible: payload.send_eligible === true,
  };
}

function isRetrievedCitation(value: unknown): value is RetrievedCitation {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const citation = value as Record<string, unknown>;
  return (
    typeof citation.rank === "number" &&
    typeof citation.document_id === "string" &&
    typeof citation.title === "string" &&
    typeof citation.document_type === "string" &&
    typeof citation.document_status === "string" &&
    typeof citation.score === "number" &&
    typeof citation.chunk_ordinal === "number" &&
    optionalNumberField(citation.char_start) &&
    optionalNumberField(citation.char_end) &&
    typeof citation.token_count === "number" &&
    optionalNumberField(citation.citation_schema_version) &&
    optionalStringField(citation.chunk_id) &&
    optionalStringField(citation.vector_id) &&
    optionalNumberField(citation.document_version) &&
    optionalStringField(citation.vector_index_name) &&
    optionalStringField(citation.safe_excerpt) &&
    optionalStringField(citation.safe_excerpt_sha256) &&
    optionalStringField(citation.chunk_content_hash)
  );
}

function optionalStringField(value: unknown): boolean {
  return value === undefined || value === null || typeof value === "string";
}

function optionalNumberField(value: unknown): boolean {
  return value === undefined || value === null || typeof value === "number";
}

function isRecommendedResolutionAction(
  value: unknown
): value is RecommendedResolutionAction {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const action = value as Record<string, unknown>;
  return (
    typeof action.type === "string" &&
    typeof action.label === "string" &&
    typeof action.requires_execution === "boolean"
  );
}

function ResolutionDraftSummary({
  draft,
  compact = false,
}: {
  draft: ResolutionOutboundDraftPayload;
  compact?: boolean;
}) {
  return (
    <div className={cn("mt-3 rounded border border-border-subtle bg-surface-sunken p-3", compact && "mt-0")}>
      <div className="mb-3 flex flex-wrap gap-2">
        <ResolutionBadge label="Draft" value={draft.status} />
        <ResolutionBadge label="Eligibility" value={draft.send_eligible ? "send eligible" : "not send eligible"} />
        <ResolutionBadge label="Confidence" value={formatConfidence(draft.confidence)} />
      </div>

      <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.18em] text-ink-tertiary">
        Outbound Draft
      </div>
      <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-ink-primary">
        {draft.draft_body}
      </p>

      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <ResolutionField label="Category" value={draft.resolution_category} />
        <ResolutionField label="Proposal" value={shortId(draft.proposal_id)} />
        <ResolutionField label="Draft hash" value={shortId(draft.draft_body_sha256)} />
        <ResolutionField label="Governance" value={draft.governance_decision_id ? shortId(draft.governance_decision_id) : "none"} />
      </div>
    </div>
  );
}

function ResolutionProposalSummary({
  proposal,
  compact = false,
}: {
  proposal: ResolutionProposalPayload;
  compact?: boolean;
}) {
  return (
    <div className={cn("mt-3 rounded border border-border-subtle bg-surface-sunken p-3", compact && "mt-0")}>
      <div className="mb-3 flex flex-wrap gap-2">
        <ResolutionBadge label="Status" value={proposal.status} />
        <ResolutionBadge label="Autonomy" value={proposal.autonomy_decision} />
        <ResolutionBadge label="Confidence" value={formatConfidence(proposal.confidence)} />
      </div>

      <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.18em] text-ink-tertiary">
        Proposed Customer Reply
      </div>
      <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-ink-primary">
        {proposal.proposed_customer_reply}
      </p>

      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <ResolutionField label="Category" value={proposal.resolution_category} />
        <ResolutionField label="Supervisor" value={proposal.supervisor_verdict} />
        <ResolutionField label="Governance" value={proposal.governance_verdict} />
        <ResolutionField label="Evidence" value={`${proposal.evidence.length} cited`} />
      </div>

      {proposal.recommended_actions.length > 0 && (
        <div className="mt-3">
          <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.18em] text-ink-tertiary">
            Recommended Actions
          </div>
          <div className="space-y-1">
            {proposal.recommended_actions.map((action) => (
              <div
                key={`${action.type}:${action.label}`}
                className="flex items-start justify-between gap-3 text-[12px]"
              >
                <span className="min-w-0 text-ink-secondary">{action.label}</span>
                <span className="shrink-0 font-technical text-[10px] uppercase tracking-[0.12em] text-ink-tertiary">
                  {action.requires_execution ? "tool" : "draft"}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ResolutionBadge({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded border border-border-subtle px-2 py-1 font-technical text-[10px] uppercase tracking-[0.12em] text-ink-secondary">
      <span className="text-ink-tertiary">{label}</span>
      <span>{formatEventLabel(value)}</span>
    </span>
  );
}

function ResolutionField({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="mb-0.5 font-mono text-[9px] uppercase tracking-[0.16em] text-ink-tertiary">
        {label}
      </div>
      <div className="truncate font-technical text-[11px] text-ink-secondary">
        {formatEventLabel(value)}
      </div>
    </div>
  );
}

function KnowledgeSources({ citations }: { citations: RetrievedCitation[] }) {
  return (
    <div className="mt-3">
      <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.18em] text-ink-tertiary">
        Knowledge Sources
      </div>
      <div className="space-y-1">
        {citations.map((citation) => {
          const showStatus =
            citation.document_status.trim() !== "" &&
            citation.document_status.toLowerCase() !== "active";

          return (
            <div
              key={`${citation.document_id}:${citation.chunk_ordinal}:${citation.rank}`}
              className="flex items-start gap-2 text-[12px]"
            >
              <span className="w-4 shrink-0 font-mono text-[11px] text-ink-tertiary">
                {citation.rank}.
              </span>
              <div className="min-w-0">
                <span className="block truncate font-medium text-ink-primary">
                  {citation.title}
                </span>
                {citation.safe_excerpt && (
                  <span className="mt-0.5 line-clamp-2 block text-[11px] leading-snug text-ink-secondary">
                    {citation.safe_excerpt}
                  </span>
                )}
                <span className="font-technical text-[11px] text-ink-tertiary">
                  {citation.document_type} · score {formatCitationScore(citation.score)}
                  {showStatus && (
                    <span className="ml-1 text-warning-amber">
                      ({citation.document_status})
                    </span>
                  )}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TraceQAScore({ score }: { score: QAScoreRecord }) {
  return (
    <section className="rounded border border-border-subtle bg-surface-sunken p-3">
      <div className="mb-3 font-mono text-[10px] uppercase tracking-[0.18em] text-ink-tertiary">
        QA Score
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <QAScoreMetric
          label="Overall"
          value={score.overall_score}
          className={qaScoreColor(score.overall_score)}
        />
        <QAScoreMetric
          label="Diagnostic accuracy"
          value={score.diagnostic_accuracy}
        />
        <QAScoreMetric
          label="Policy compliance"
          value={score.policy_compliance}
        />
        <QAScoreMetric
          label="Resolution quality"
          value={score.resolution_quality}
        />
      </div>
    </section>
  );
}

function QAScoreMetric({
  label,
  value,
  className,
}: {
  label: string;
  value: number;
  className?: string;
}) {
  return (
    <div className="min-w-0 rounded border border-border-subtle px-3 py-2">
      <div className="truncate font-mono text-[9px] uppercase tracking-[0.16em] text-ink-tertiary">
        {label}
      </div>
      <div className={cn("mt-1 font-technical text-[13px] text-ink-primary", className)}>
        {value.toFixed(2)}
      </div>
    </div>
  );
}

function RawJsonModal({
  response,
  onClose,
  onCopy,
}: {
  response: SessionTimelineResponse;
  onClose: () => void;
  onCopy: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Raw timeline JSON"
        className="flex max-h-[86vh] w-full max-w-4xl flex-col rounded-lg border border-border-subtle bg-surface-raised shadow-2xl"
      >
        <div className="flex items-center justify-between border-b border-border-subtle px-4 py-3">
          <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-ink-tertiary">
            Raw Timeline Response
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onCopy}
              className="flex h-10 w-10 items-center justify-center rounded transition-colors hover:bg-surface-sunken"
              aria-label="Copy raw timeline JSON"
            >
              <Copy className="h-4 w-4 text-ink-secondary" strokeWidth={1.5} />
            </button>
            <button
              type="button"
              onClick={onClose}
              className="flex h-10 w-10 items-center justify-center rounded transition-colors hover:bg-surface-sunken"
              aria-label="Close raw timeline JSON"
            >
              <X className="h-4 w-4 text-ink-secondary" strokeWidth={1.5} />
            </button>
          </div>
        </div>
        <pre className="overflow-auto p-4 text-[11px] leading-relaxed text-ink-secondary">
          {JSON.stringify(response, null, 2)}
        </pre>
      </div>
    </div>
  );
}

function JsonTree({ value }: { value: unknown }) {
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="font-mono text-[11px] text-ink-tertiary">[]</span>;
    return (
      <div className="space-y-1 pl-3">
        {value.map((item, index) => (
          <div key={index} className="font-mono text-[11px] leading-relaxed text-ink-secondary">
            <span className="text-ink-tertiary">[{index}]</span>{" "}
            <JsonTree value={item} />
          </div>
        ))}
      </div>
    );
  }

  if (value && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return <span className="font-mono text-[11px] text-ink-tertiary">{"{}"}</span>;
    return (
      <div className="space-y-1 pl-3">
        {entries.map(([key, item]) => (
          <div key={key} className="font-mono text-[11px] leading-relaxed text-ink-secondary">
            <span className="text-gold-primary">{key}</span>: <JsonTree value={item} />
          </div>
        ))}
      </div>
    );
  }

  return <span className="font-mono text-[11px] text-ink-primary">{stringifyValue(value)}</span>;
}

function MetadataField({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="flex-1 px-4 first:pl-0 last:pr-0">
      <div className="mb-1 font-mono text-[10px] uppercase tracking-[0.18em] text-ink-tertiary">
        {label}
      </div>
      {typeof value === "string" ? (
        <div className={cn("text-[13px] font-medium text-ink-primary", mono ? "font-mono" : "font-sans")}>
          {value}
        </div>
      ) : (
        value
      )}
    </div>
  );
}

function Divider() {
  return <div className="mx-2 w-px self-stretch bg-border-subtle" />;
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="mb-1 font-mono text-[10px] uppercase tracking-[0.18em] text-ink-tertiary">
        {label}
      </div>
      <div className="break-words font-mono text-[13px] text-ink-primary">
        {value}
      </div>
    </div>
  );
}

function Metric({ icon, value }: { icon: ReactNode; value: string }) {
  return (
    <div className="flex min-w-0 items-center gap-2">
      <span className="text-ink-tertiary">{icon}</span>
      <span className="truncate font-mono text-[13px] text-ink-primary">
        {value}
      </span>
    </div>
  );
}

function deriveTraceMetadata(
  sessionId: string | null,
  events: TimelineEventView[]
) {
  if (events.length === 0) {
    return {
      tenantId: "No tenant",
      firstEvent: sessionId ? "No events" : "No session",
      duration: "No events",
    };
  }

  const first = events[0];
  const last = events[events.length - 1];
  const startedAt = new Date(first.timestamp).getTime();
  const endedAt = new Date(last.timestamp).getTime();
  return {
    tenantId: first.tenant_id ?? "No tenant",
    firstEvent: formatEventLabel(first.event_type),
    duration:
      Number.isNaN(startedAt) || Number.isNaN(endedAt)
        ? "Unknown"
        : formatDuration(Math.max(0, endedAt - startedAt)),
  };
}

function colorForEventType(eventType: string): string {
  if (eventType.startsWith("diagnostic_")) return "#1A4A9A";
  if (eventType.startsWith("resolution_")) return "#0F766E";
  if (eventType.startsWith("governance_")) return "#C9A84C";
  if (eventType.startsWith("session_")) return "#8A93A4";
  if (eventType.startsWith("escalation_")) return "#B8821C";
  if (eventType.startsWith("sop_")) return "#7C3AED";
  return "#8A93A4";
}

function formatEventLabel(eventType: string): string {
  return eventType.replaceAll("_", " ");
}

function formatRelativeTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "unknown";

  const diffMs = Date.now() - date.getTime();
  const absMs = Math.abs(diffMs);
  const units = [
    { label: "d", ms: 86_400_000 },
    { label: "h", ms: 3_600_000 },
    { label: "m", ms: 60_000 },
  ];

  for (const unit of units) {
    if (absMs >= unit.ms) {
      const valueInUnit = Math.floor(absMs / unit.ms);
      return diffMs >= 0 ? `${valueInUnit}${unit.label} ago` : `in ${valueInUnit}${unit.label}`;
    }
  }

  return diffMs >= 0 ? "just now" : "in less than 1m";
}

function formatAbsoluteTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Invalid date";
  return date.toISOString();
}

function formatDuration(milliseconds: number): string {
  if (milliseconds < 1000) return `${Math.round(milliseconds)}ms`;
  const totalSeconds = Math.round(milliseconds / 1000);
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}m ${seconds}s`;
}

function shortId(value: string): string {
  if (value.length <= 14) return value;
  return `${value.slice(0, 8)}...${value.slice(-4)}`;
}

function stringifyValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (value === null || value === undefined) return "null";
  return JSON.stringify(value);
}

function formatCitationScore(score: number): string {
  if (!Number.isFinite(score)) return String(score);
  return score.toFixed(4);
}

function formatConfidence(value: number): string {
  if (!Number.isFinite(value)) return "unknown";
  return `${Math.round(value * 100)}%`;
}

function qaScoreColor(score: number): string {
  if (score >= 0.85) return "text-green-500";
  if (score >= 0.75) return "text-amber-500";
  return "text-red-500";
}

function stringField(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function numberField(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}
