/**
 * @operious/contracts
 *
 * Pinned API surface descriptions.
 *
 * This package is the SINGLE source of truth for endpoint paths, HTTP methods,
 * request shapes, and response shapes. The SDK reads from here. UI components
 * NEVER call `fetch` directly — they always go through SDK hooks that resolve
 * to one of these contracts.
 *
 * Authority: backend.
 * Visibility: read-only.
 *
 * Wire-format discipline: the contract paths below are pinned alongside backend
 * route registration. Drift is intentionally a type-check failure.
 */

export * from './endpoints';
export * from './queries';
export * from './mutations';
