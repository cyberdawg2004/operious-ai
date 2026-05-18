import type { TraceBundleDto, TraceNodeDto } from '@operious/types';
import { stableSortBy } from '@operious/shared';

/**
 * Deterministic chronological ordering of trace nodes.
 *
 * Tie-break order:
 *   1. observedAt (ISO-8601 UTC) ascending
 *   2. lineage.sequence ascending
 *   3. payload.observedAt secondary
 *
 * The backend already emits nodes in canonical order, but the frontend
 * re-sorts defensively so navigation, filtering, or partial loading can
 * never rearrange forensic evidence.
 */
export const renderableTraceNodes = (
  bundle: TraceBundleDto,
): readonly TraceNodeDto[] =>
  stableSortBy([...bundle.nodes], (node) => {
    const payload = node.payload as { observedAt?: string; lineage?: { sequence?: number } };
    const observedAt = payload.observedAt ?? '';
    const sequence = payload.lineage?.sequence ?? 0;
    return `${observedAt}|${sequence.toString().padStart(10, '0')}|${node.kind}`;
  });
