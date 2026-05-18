/**
 * @operious/auth
 *
 * FRONTEND AUTH FOUNDATIONS ONLY.
 *
 * This package intentionally does NOT implement:
 *   - real auth providers
 *   - session token negotiation
 *   - silent refresh
 *   - role-based authorization decisions
 *
 * The backend owns all authority. The frontend's only job here is to:
 *   - hold the current principal identity (read-only) for display purposes
 *   - expose a hook for SDK calls to attach an auth header that the backend validates
 *
 * Authorization is NEVER computed in the frontend. UI gating is purely
 * presentational; the backend re-checks every request and is the source of truth.
 */

export { AuthProvider, buildPrincipal, useAuth, useAuthHeader } from './context';
export type { AuthContextValue, AuthPrincipal } from './context';
