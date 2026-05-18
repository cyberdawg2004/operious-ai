/**
 * @operious/observability
 *
 * Frontend trace / lineage / replay visualization helpers.
 *
 * IMPORTANT: this package never re-derives lineage. It only renders what the
 * backend persisted. Replay visualization in particular treats backend
 * `replayDigest` values as opaque, deterministic identifiers — the frontend
 * compares them with strict string equality, never recomputes them.
 */

export { TraceTimeline } from './trace-timeline';
export { ReplayEvidence } from './replay-evidence';
export { LineageRibbon } from './lineage-ribbon';
export { renderableTraceNodes } from './ordering';
