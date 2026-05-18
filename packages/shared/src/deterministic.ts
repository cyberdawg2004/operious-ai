/**
 * Deterministic frontend rendering helpers.
 *
 * The frontend MUST render lists in deterministic order. We do not allow
 * implicit insertion-order rendering of operational artifacts because that
 * couples UI ordering to upstream nondeterminism (network arrival, cache
 * eviction, optimistic updates we explicitly forbid).
 *
 * All renderers in @operious/ui call into these helpers.
 */

/**
 * Stable sort by a string key extractor.
 * Returns a NEW array; never mutates input. Frontend DTOs are immutable.
 */
export const stableSortBy = <T>(items: readonly T[], key: (item: T) => string): T[] => {
  const indexed = items.map((item, index) => ({ item, index, key: key(item) }));
  indexed.sort((a, b) => {
    if (a.key < b.key) return -1;
    if (a.key > b.key) return 1;
    return a.index - b.index;
  });
  return indexed.map((entry) => entry.item);
};

/**
 * Stable chronological sort by an ISO-8601 timestamp extractor.
 * Equal timestamps preserve original order — this is the deterministic
 * tie-break required for replay-safe rendering of timeline events.
 */
export const chronological = <T>(items: readonly T[], at: (item: T) => string): T[] =>
  stableSortBy(items, at);

/**
 * Compare two ISO-8601 timestamps deterministically.
 * Returns -1, 0, or 1. Does not throw for malformed input — the frontend
 * never raises during render.
 */
export const compareIsoTimestamps = (a: string, b: string): number => {
  if (a === b) return 0;
  return a < b ? -1 : 1;
};

/**
 * Canonicalize a JSON-serializable value for stable rendering / hashing.
 * Object keys are sorted recursively.
 */
export const canonicalize = (value: unknown): unknown => {
  if (value === null || typeof value !== 'object') return value;
  if (Array.isArray(value)) return value.map((item) => canonicalize(item));
  const entries = Object.entries(value as Record<string, unknown>)
    .map(([k, v]) => [k, canonicalize(v)] as const)
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  return Object.fromEntries(entries);
};

export const canonicalJson = (value: unknown): string =>
  JSON.stringify(canonicalize(value));
