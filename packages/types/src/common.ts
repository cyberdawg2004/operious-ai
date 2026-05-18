import type { CorrelationId, TenantId } from './ids';

/**
 * Common shapes shared across substrate DTOs.
 */

/**
 * ISO-8601 UTC timestamp string. Backend pins UTC timezone-aware datetimes.
 * The frontend never adjusts offsets — display is always UTC unless the
 * UX explicitly localises it (a presentation concern, not a cognition concern).
 */
export type IsoTimestamp = string;

/**
 * Lineage envelope shared across substrates.
 * `parentCorrelationId` may be absent for root-level artifacts.
 */
export interface Lineage {
  readonly correlationId: CorrelationId;
  readonly parentCorrelationId?: CorrelationId;
  readonly tenantId?: TenantId;
  readonly sequence: number;
  readonly observedAt: IsoTimestamp;
}

/**
 * Generic backend error envelope. The backend never raises across the wire;
 * this is the shape the frontend renders for failed operations.
 */
export interface ErrorEnvelope {
  readonly code: string;
  readonly message: string;
  readonly substrate: string;
  readonly correlationId?: CorrelationId;
  readonly observedAt: IsoTimestamp;
}

/**
 * Pagination cursor used uniformly by every list endpoint.
 * The cursor is opaque to the frontend.
 */
export interface PaginationCursor {
  readonly cursor?: string;
  readonly limit: number;
}

export interface Page<T> {
  readonly items: readonly T[];
  readonly nextCursor?: string;
  readonly observedAt: IsoTimestamp;
}
