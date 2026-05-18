/**
 * Frontend invariant helpers.
 *
 * `assertOperationalDiscipline` is the explicit gate at the frontend boundary
 * that refuses to render objects that the backend marks as not yet authoritative.
 *
 * The frontend NEVER overrides backend authority. If the backend hasn't yet
 * confirmed a mutation, we render a "pending" state — never an optimistic state
 * pretending the mutation is real.
 */

export class FrontendInvariantError extends Error {
  constructor(message: string) {
    super(`[operious/invariant] ${message}`);
    this.name = 'FrontendInvariantError';
  }
}

export const invariant = (condition: unknown, message: string): asserts condition => {
  if (!condition) {
    throw new FrontendInvariantError(message);
  }
};

/**
 * Frozen-deep-clone for treating server DTOs as immutable.
 * The frontend never mutates a DTO it received from the backend.
 */
export const freezeDeep = <T>(value: T): T => {
  if (value === null || typeof value !== 'object') return value;
  Object.values(value as Record<string, unknown>).forEach((entry) => {
    if (entry !== null && typeof entry === 'object' && !Object.isFrozen(entry)) {
      freezeDeep(entry);
    }
  });
  return Object.freeze(value);
};
