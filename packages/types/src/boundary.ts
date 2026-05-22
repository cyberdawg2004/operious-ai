import type { IsoTimestamp, Lineage } from './common';
import type {
  CorrelationId,
  PrincipalId,
  SessionId,
  TenantId,
} from './ids';

/**
 * Boundary substrate DTO mirror.
 *
 * The boundary is a TRANSLATION substrate — it observes external events
 * and emits external mutations. It NEVER orchestrates downstream behaviour
 * and NEVER produces operational truth on its own.
 *
 * Wire-format pinning: every value in this file matches the backend
 * `apps/backend/app/boundary/enums.py` byte-for-byte (verified by
 * `tests-frontend/src/wire-format-pinning.test.ts`).
 *
 * External vocabularies (Zendesk/WhatsApp/Twilio/…) are mapped INTO this
 * canonical vocabulary at the adapter boundary; the substrate never
 * re-exports raw external strings.
 */

/**
 * Wire-pinned mirror of `BoundaryDirection`.
 */
export const BoundaryDirection = {
  INGRESS: 'ingress',
  EGRESS: 'egress',
} as const;
export type BoundaryDirection =
  (typeof BoundaryDirection)[keyof typeof BoundaryDirection];

/**
 * Wire-pinned mirror of `BoundarySourceType`.
 */
export const BoundarySourceType = {
  ZENDESK: 'zendesk',
  WHATSAPP: 'whatsapp',
  TWILIO_VOICE: 'twilio_voice',
  TWILIO_SMS: 'twilio_sms',
  EMAIL: 'email',
  SLACK: 'slack',
  LARK: 'lark',
  SHULEX: 'shulex',
  REST_API: 'rest_api',
  GENERIC: 'generic',
} as const;
export type BoundarySourceType =
  (typeof BoundarySourceType)[keyof typeof BoundarySourceType];

/**
 * Wire-pinned mirror of `BoundaryMessageType`.
 */
export const BoundaryMessageType = {
  MESSAGE_RECEIVED: 'message_received',
  MESSAGE_DELIVERED: 'message_delivered',
  STATUS_UPDATE: 'status_update',
  EVENT_CREATED: 'event_created',
  EVENT_UPDATED: 'event_updated',
  STREAM_FRAME: 'stream_frame',
  PRESENCE_UPDATE: 'presence_update',
  UNKNOWN: 'unknown',
} as const;
export type BoundaryMessageType =
  (typeof BoundaryMessageType)[keyof typeof BoundaryMessageType];

/**
 * Wire-pinned mirror of `BoundaryNormalizationStatus`.
 */
export const BoundaryNormalizationStatus = {
  OK: 'ok',
  MALFORMED: 'malformed',
  UNAUTHENTICATED: 'unauthenticated',
  UNSUPPORTED_TYPE: 'unsupported_type',
  ADAPTER_ERROR: 'adapter_error',
} as const;
export type BoundaryNormalizationStatus =
  (typeof BoundaryNormalizationStatus)[keyof typeof BoundaryNormalizationStatus];

/**
 * Wire-pinned mirror of `BoundaryReplayDisposition`.
 */
export const BoundaryReplayDisposition = {
  NEW: 'new',
  REPLAY_OF_KNOWN: 'replay_of_known',
  LINEAGE_DRIFT: 'lineage_drift',
  INVALID_KEY: 'invalid_key',
} as const;
export type BoundaryReplayDisposition =
  (typeof BoundaryReplayDisposition)[keyof typeof BoundaryReplayDisposition];

/**
 * Minimal apex trace shape rendered by the Trace Inspector.
 *
 * Direction-tagged so a single DTO mirrors both `BoundaryIngressRuntime`
 * and `BoundaryEgressRuntime` emissions without losing the distinction.
 *
 * Mirrors `BoundaryTrace` in `apps/backend/app/boundary/tracing.py`. Only
 * the subset of fields the timeline renderer needs is projected; backend
 * persistence carries the full record and audit surfaces can fetch it on
 * demand by `traceId`.
 */
export interface BoundaryTraceDto {
  readonly traceId: string;
  readonly direction: BoundaryDirection;
  readonly sourceType: BoundarySourceType;
  readonly sourceId: string;
  readonly adapterName: string;
  readonly observedAt: IsoTimestamp;
  readonly latencyMs: number;
  readonly tenantId?: TenantId;
  readonly principalId?: PrincipalId;
  readonly sessionId?: SessionId;
  readonly correlationId?: CorrelationId;
  readonly normalizationStatus?: BoundaryNormalizationStatus;
  readonly replayDisposition?: BoundaryReplayDisposition;
  readonly tenantAuthoritySource?: string;
  readonly error?: string;
  readonly lineage: Lineage;
}
