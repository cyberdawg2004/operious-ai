import type { Brand } from '@operious/shared';

/**
 * Branded substrate identifiers.
 *
 * Mirrors backend `NewType(...)` discipline. The frontend MUST NOT mix IDs
 * across substrates — the type system refuses the assignment.
 *
 * Backend canonical authority for derivation lives in `app/<substrate>/identity/`.
 * The frontend never derives identifiers — it only displays them.
 */

export type SessionId = Brand<string, 'SessionId'>;
export type SessionEventId = Brand<string, 'SessionEventId'>;
export type CorrelationId = Brand<string, 'CorrelationId'>;

export type GovernanceEvaluationId = Brand<string, 'GovernanceEvaluationId'>;
export type GovernanceTraceId = Brand<string, 'GovernanceTraceId'>;

export type ArbitrationCaseId = Brand<string, 'ArbitrationCaseId'>;
export type ArbitrationDecisionId = Brand<string, 'ArbitrationDecisionId'>;

export type TopologyEvaluationId = Brand<string, 'TopologyEvaluationId'>;
export type TopologyNodeId = Brand<string, 'TopologyNodeId'>;
export type TopologyEdgeId = Brand<string, 'TopologyEdgeId'>;

export type AgentId = Brand<string, 'AgentId'>;
export type AgentExecutionId = Brand<string, 'AgentExecutionId'>;

export type SOPProposalId = Brand<string, 'SOPProposalId'>;
export type MemoryProposalId = Brand<string, 'MemoryProposalId'>;
export type RecommendationId = Brand<string, 'RecommendationId'>;
export type ApprovalRecordId = Brand<string, 'ApprovalRecordId'>;

export type TenantId = Brand<string, 'TenantId'>;
export type PrincipalId = Brand<string, 'PrincipalId'>;
