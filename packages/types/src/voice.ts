import type { IsoTimestamp, Lineage } from './common';
import type { CorrelationId, TenantId } from './ids';

/**
 * Voice-substrate DTO mirror.
 *
 * Voice is BOUNDARY INFRASTRUCTURE. It MUST NEVER influence
 * governance, mutate cognition, change operational meaning, or
 * inject orchestration logic.
 *
 * Wire-format pinning: every value below matches the backend
 * `apps/backend/app/boundary/voice/enums.py` byte-for-byte
 * (verified by `tests-frontend/src/wire-format-pinning.test.ts`).
 */

/**
 * Wire-pinned mirror of `VoiceDirection`.
 */
export const VoiceDirection = {
  INGRESS: 'ingress',
  EGRESS: 'egress',
} as const;
export type VoiceDirection =
  (typeof VoiceDirection)[keyof typeof VoiceDirection];

/**
 * Wire-pinned mirror of `VoiceStatus`.
 */
export const VoiceStatus = {
  PENDING: 'pending',
  NORMALIZED: 'normalized',
  TRANSCRIBED: 'transcribed',
  SYNTHESIZED: 'synthesized',
  COMPLETED: 'completed',
  REJECTED: 'rejected',
  ERRORED: 'errored',
} as const;
export type VoiceStatus = (typeof VoiceStatus)[keyof typeof VoiceStatus];

/**
 * Wire-pinned mirror of `VoiceProviderKind`.
 */
export const VoiceProviderKind = {
  DETERMINISTIC_STUB: 'deterministic_stub',
  EXTERNAL: 'external',
} as const;
export type VoiceProviderKind =
  (typeof VoiceProviderKind)[keyof typeof VoiceProviderKind];

/**
 * Wire-pinned mirror of `AudioFormat`.
 *
 * Bounded vocabulary of audio container/codec hints.
 */
export const AudioFormat = {
  PCM_S16LE: 'pcm_s16le',
  PCM_F32LE: 'pcm_f32le',
  OPUS: 'opus',
  MP3: 'mp3',
  G711_ALAW: 'g711_alaw',
  G711_MULAW: 'g711_mulaw',
  WAV: 'wav',
  OGG: 'ogg',
  UNKNOWN: 'unknown',
} as const;
export type AudioFormat = (typeof AudioFormat)[keyof typeof AudioFormat];

/**
 * Wire-pinned mirror of `VoiceFindingKind`.
 */
export const VoiceFindingKind = {
  OK: 'ok',
  UNVERIFIED_PROVIDER: 'unverified_provider',
  LOW_CONFIDENCE: 'low_confidence',
  EMPTY_TRANSCRIPT: 'empty_transcript',
  REPLAY_DRIFT: 'replay_drift',
} as const;
export type VoiceFindingKind =
  (typeof VoiceFindingKind)[keyof typeof VoiceFindingKind];

/**
 * Wire-pinned mirror of `VoiceTraceKind`.
 */
export const VoiceTraceKind = {
  INGRESS_TRANSCRIBE: 'ingress_transcribe',
  EGRESS_SYNTHESIZE: 'egress_synthesize',
  GET_INGRESS: 'get_ingress',
  GET_EGRESS: 'get_egress',
} as const;
export type VoiceTraceKind =
  (typeof VoiceTraceKind)[keyof typeof VoiceTraceKind];

/**
 * Minimal apex trace shape rendered by the Trace Inspector.
 *
 * Mirrors `VoiceTrace` in `boundary/voice/traces/trace.py`.
 */
export interface VoiceTraceDto {
  readonly traceId: string;
  readonly kind: VoiceTraceKind;
  readonly observedAt: IsoTimestamp;
  readonly latencyMs: number;
  readonly tenantId?: TenantId;
  readonly correlationId?: CorrelationId;
  readonly providerName?: string;
  readonly tenantAuthoritySource?: string;
  readonly error?: string;
  readonly lineage: Lineage;
}
