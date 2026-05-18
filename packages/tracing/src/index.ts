/**
 * @operious/tracing
 *
 * Frontend tracing helpers — correlation-id generation for client requests,
 * lineage continuity rendering helpers, and trace key derivation.
 *
 * IMPORTANT: This package generates only CLIENT correlation IDs. They are
 * suggestions to the backend — the backend remains the authority over
 * canonical correlation continuity. The frontend NEVER asserts a backend
 * correlation id; it only displays what the backend returned.
 */

import { brand, type Brand } from '@operious/shared';
import type { CorrelationId, IsoTimestamp, Lineage } from '@operious/types';

/**
 * Generate a deterministic-shaped client correlation id.
 *
 * Uses `crypto.randomUUID` when available (modern browsers / Node 20+).
 * Falls back to a sortable opaque string. The shape is unimportant to the
 * backend — it accepts any string and re-derives canonical lineage internally.
 */
export const newClientCorrelationId = (): CorrelationId => {
  if (typeof globalThis.crypto !== 'undefined' && globalThis.crypto.randomUUID) {
    return brand<'CorrelationId'>(globalThis.crypto.randomUUID());
  }
  // Deterministic fallback — never used in production browsers.
  const ts = Date.now().toString(36);
  const rnd = Math.floor(Math.random() * 1e9).toString(36);
  return brand<'CorrelationId'>(`fe-${ts}-${rnd}`);
};

/**
 * Format a lineage envelope for compact display.
 * Returns `seq#3 · 2026-05-15T12:34:56Z` style.
 */
export const formatLineage = (lineage: Lineage): string =>
  `seq#${lineage.sequence} · ${lineage.observedAt}`;

/**
 * Compute a deterministic React key for any lineage-bearing artifact.
 * `correlationId+sequence` is sufficient because lineage envelopes are
 * always backend-authoritative and immutable.
 */
export const lineageKey = (lineage: Lineage): string =>
  `${lineage.correlationId}@${lineage.sequence}`;

export type ClientRequestId = Brand<string, 'ClientRequestId'>;

export const newClientRequestId = (): ClientRequestId =>
  brand<'ClientRequestId'>(
    typeof globalThis.crypto !== 'undefined' && globalThis.crypto.randomUUID
      ? globalThis.crypto.randomUUID()
      : `req-${Date.now()}-${Math.floor(Math.random() * 1e9)}`,
  );

export const headerForCorrelation = (correlationId: CorrelationId): Record<string, string> => ({
  'x-operious-correlation-id': correlationId as unknown as string,
});

export const isoNow = (): IsoTimestamp => new Date().toISOString();
