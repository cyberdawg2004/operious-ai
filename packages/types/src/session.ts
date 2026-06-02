import type { IsoTimestamp, Lineage } from './common';
import type {
  CorrelationId,
  PrincipalId,
  SessionEventId,
  SessionId,
  TenantId,
} from './ids';

/**
 * Session substrate DTO mirror.
 *
 * Pinned wire values match `apps/backend/app/session/enums.py`. Renaming a
 * value here is a breaking change to every previously persisted session record.
 */

export const SessionLifecyclePhase = {
  INITIATED: 'initiated',
  ACTIVE: 'active',
  DORMANT: 'dormant',
  TERMINATED: 'terminated',
  ARCHIVED: 'archived',
} as const;
export type SessionLifecyclePhase =
  (typeof SessionLifecyclePhase)[keyof typeof SessionLifecyclePhase];

export const SessionScope = {
  TENANT: 'tenant',
  PRINCIPAL: 'principal',
  OPERATIONAL_DOMAIN: 'operational_domain',
  GLOBAL: 'global',
} as const;
export type SessionScope = (typeof SessionScope)[keyof typeof SessionScope];

export const SessionEventKind = {
  SESSION_OPENED: 'session_opened',
  CONTEXT_ATTACHED: 'context_attached',
  CORRELATION_RECORDED: 'correlation_recorded',
  LINEAGE_LINKED: 'lineage_linked',
  LIFECYCLE_RECLASSIFIED: 'lifecycle_reclassified',
  DORMANCY_RECORDED: 'dormancy_recorded',
  RESUMPTION_RECORDED: 'resumption_recorded',
  TERMINATION_RECORDED: 'termination_recorded',
  ARCHIVAL_RECORDED: 'archival_recorded',
  OPERATIONAL_OBSERVATION: 'operational_observation',
  CUSTOMER_MESSAGE: 'customer_message',
  ASSISTANT_RESPONSE: 'assistant_response',
} as const;
export type SessionEventKind =
  (typeof SessionEventKind)[keyof typeof SessionEventKind];

export const SessionContinuityMode = {
  SYNCHRONOUS: 'synchronous',
  DEFERRED: 'deferred',
  RECONSTRUCTED: 'reconstructed',
} as const;
export type SessionContinuityMode =
  (typeof SessionContinuityMode)[keyof typeof SessionContinuityMode];

export const SessionCorrelationKind = {
  GOVERNANCE: 'governance',
  TOPOLOGY: 'topology',
  POLICY: 'policy',
  COORDINATION: 'coordination',
  AGENT_EXECUTION: 'agent_execution',
  SUPERVISOR: 'supervisor',
  ARBITRATION: 'arbitration',
  BOUNDARY: 'boundary',
  MEMORY: 'memory',
  EXTERNAL: 'external',
  GENERIC: 'generic',
} as const;
export type SessionCorrelationKind =
  (typeof SessionCorrelationKind)[keyof typeof SessionCorrelationKind];

export interface SessionTimelineEventDto {
  readonly eventId: SessionEventId;
  readonly sessionId: SessionId;
  readonly sequence: number;
  readonly kind: SessionEventKind;
  readonly continuityMode: SessionContinuityMode;
  readonly observedAt: IsoTimestamp;
  readonly correlationId: CorrelationId;
  readonly summary: string;
  readonly payload: Readonly<Record<string, unknown>>;
}

export interface OperationalSessionDto {
  readonly sessionId: SessionId;
  readonly scope: SessionScope;
  readonly lifecyclePhase: SessionLifecyclePhase;
  readonly tenantId?: TenantId;
  readonly principalId?: PrincipalId;
  readonly openedAt: IsoTimestamp;
  readonly lastActivityAt: IsoTimestamp;
  readonly eventCount: number;
  readonly lineage: Lineage;
}
