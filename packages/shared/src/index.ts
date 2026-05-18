/**
 * @operious/shared
 *
 * Deterministic primitive utilities shared by every frontend package.
 *
 * THIS PACKAGE MUST NEVER:
 *   - hold operational state
 *   - mutate runtime semantics
 *   - perform orchestration
 *   - own authority
 *
 * It only provides:
 *   - immutable helpers
 *   - deterministic ordering helpers
 *   - canonical comparators
 *   - branded identity primitives
 */

export * from './brand';
export * from './deterministic';
export * from './result';
export * from './invariant';
