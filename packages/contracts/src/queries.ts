import type {
  ApprovalRecordDto,
  ArbitrationCaseId,
  CorrelationId,
  GovernanceTraceDto,
  GovernanceTraceId,
  MemoryProposalDto,
  Page,
  QueueItemDto,
  QueueItemKind,
  QueueItemStatus,
  RecommendationDto,
  SOPProposalDto,
  SessionId,
  SessionTimelineEventDto,
  TopologyGraphDto,
  TraceBundleDto,
} from '@operious/types';

/**
 * Pinned query contracts.
 *
 * Every read-only API call has an explicit Query type and an explicit
 * QueryResult shape. The SDK resolves these types into TanStack Query keys.
 */

// ---- operations queue ----

export interface OperationsQueueQuery {
  readonly status?: QueueItemStatus;
  readonly kind?: QueueItemKind;
  readonly cursor?: string;
  readonly limit?: number;
}
export type OperationsQueueResult = Page<QueueItemDto>;

// ---- traces ----

export interface TraceBundleQuery {
  readonly correlationId: CorrelationId;
}
export type TraceBundleResult = TraceBundleDto;

export interface SessionTimelineQuery {
  readonly sessionId: SessionId;
}
export type SessionTimelineResult = {
  readonly sessionId: SessionId;
  readonly events: readonly SessionTimelineEventDto[];
};

// ---- governance ----

export interface GovernanceTraceQuery {
  readonly traceId: GovernanceTraceId;
}
export type GovernanceTraceResult = GovernanceTraceDto;

export interface GovernanceTraceListQuery {
  readonly cursor?: string;
  readonly limit?: number;
}
export type GovernanceTraceListResult = Page<GovernanceTraceDto>;

// ---- cognition ----

export interface ProposalListQuery {
  readonly cursor?: string;
  readonly limit?: number;
}
export type MemoryProposalListResult = Page<MemoryProposalDto>;
export type SOPProposalListResult = Page<SOPProposalDto>;
export type RecommendationListResult = Page<RecommendationDto>;
export type ApprovalRecordListResult = Page<ApprovalRecordDto>;

// ---- topology ----

export interface TopologyGraphQuery {
  readonly version?: string;
}
export type TopologyGraphResult = TopologyGraphDto;

// re-export the input id types to keep contracts self-contained
export type { ArbitrationCaseId, CorrelationId, GovernanceTraceId, SessionId };
