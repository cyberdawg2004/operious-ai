import type { IsoTimestamp, Lineage } from './common';
import type { CorrelationId, TenantId } from './ids';

/**
 * Translation-substrate DTO mirror.
 *
 * Translation is BOUNDARY INFRASTRUCTURE. It translates representation
 * only — it MUST NEVER change governance, escalation, authority,
 * compliance, or SOP semantics.
 *
 * Wire-format pinning: every value below matches the backend
 * `apps/backend/app/boundary/translation/enums.py` byte-for-byte
 * (verified by `tests-frontend/src/wire-format-pinning.test.ts`).
 */

/**
 * Wire-pinned mirror of `TranslationDirection`.
 */
export const TranslationDirection = {
  INGRESS: 'ingress',
  EGRESS: 'egress',
} as const;
export type TranslationDirection =
  (typeof TranslationDirection)[keyof typeof TranslationDirection];

/**
 * Wire-pinned mirror of `TranslationStatus`.
 */
export const TranslationStatus = {
  PENDING: 'pending',
  NORMALIZED: 'normalized',
  TRANSLATED: 'translated',
  VALIDATED: 'validated',
  LOCALIZED: 'localized',
  COMPLETED: 'completed',
  REJECTED: 'rejected',
  ERRORED: 'errored',
} as const;
export type TranslationStatus =
  (typeof TranslationStatus)[keyof typeof TranslationStatus];

/**
 * Wire-pinned mirror of `TranslationProviderKind`.
 */
export const TranslationProviderKind = {
  IDENTITY: 'identity',
  DETERMINISTIC_STUB: 'deterministic_stub',
  EXTERNAL: 'external',
} as const;
export type TranslationProviderKind =
  (typeof TranslationProviderKind)[keyof typeof TranslationProviderKind];

/**
 * Wire-pinned mirror of `SemanticPreservationStatus`.
 */
export const SemanticPreservationStatus = {
  PRESERVED: 'preserved',
  DRIFTED: 'drifted',
  SUSPICIOUS: 'suspicious',
  UNVERIFIABLE: 'unverifiable',
} as const;
export type SemanticPreservationStatus =
  (typeof SemanticPreservationStatus)[keyof typeof SemanticPreservationStatus];

/**
 * Wire-pinned mirror of `LocalizationFormality`.
 *
 * Descriptive metadata only. Localization MUST NOT touch
 * governance / escalation semantics.
 */
export const LocalizationFormality = {
  NEUTRAL: 'neutral',
  FORMAL: 'formal',
  INFORMAL: 'informal',
} as const;
export type LocalizationFormality =
  (typeof LocalizationFormality)[keyof typeof LocalizationFormality];

/**
 * Wire-pinned mirror of `TranslationFindingKind`.
 */
export const TranslationFindingKind = {
  OK: 'ok',
  UNVERIFIED_PROVIDER: 'unverified_provider',
  SEMANTIC_DRIFT: 'semantic_drift',
  NORMALIZATION_DRIFT: 'normalization_drift',
  PROHIBITED_TOKEN_LOSS: 'prohibited_token_loss',
  PROHIBITED_TOKEN_INJECTED: 'prohibited_token_injected',
  REPLAY_DRIFT: 'replay_drift',
} as const;
export type TranslationFindingKind =
  (typeof TranslationFindingKind)[keyof typeof TranslationFindingKind];

/**
 * Wire-pinned mirror of `TranslationTraceKind`.
 *
 * One value per translation-runtime method.
 */
export const TranslationTraceKind = {
  INGRESS_TRANSLATE: 'ingress_translate',
  EGRESS_LOCALIZE: 'egress_localize',
  GET_INGRESS: 'get_ingress',
  GET_EGRESS: 'get_egress',
} as const;
export type TranslationTraceKind =
  (typeof TranslationTraceKind)[keyof typeof TranslationTraceKind];

/**
 * Canonical operational cognition language. Pinned to backend
 * `CANONICAL_LANGUAGE = "en"` in `boundary/translation/enums.py`.
 */
export const CANONICAL_LANGUAGE = 'en' as const;
export type CanonicalLanguage = typeof CANONICAL_LANGUAGE;

/**
 * Minimal apex trace shape rendered by the Trace Inspector.
 *
 * Mirrors `TranslationTrace` in `boundary/translation/traces/trace.py`.
 */
export interface TranslationTraceDto {
  readonly traceId: string;
  readonly kind: TranslationTraceKind;
  readonly observedAt: IsoTimestamp;
  readonly latencyMs: number;
  readonly tenantId?: TenantId;
  readonly correlationId?: CorrelationId;
  readonly providerName?: string;
  readonly tenantAuthoritySource?: string;
  readonly error?: string;
  readonly lineage: Lineage;
}
