/**
 * Platform access gate (Phase 2.5d-platform-scaffold).
 *
 * The ENTIRE Platform Console gates on platform.tenant.admin. This is the core
 * of the "for us" surface: a tenant operator who reaches the URL sees a
 * refusal, never platform tooling.
 *
 * React-free so the gate decision is unit-testable against mocked /auth/me.
 * (The hasPlatformAdmin helper mirrors the onboarding-state.ts pattern; the
 * onboarding code itself moves in the next spec, so it is defined locally.)
 */

import type { AuthPrincipal } from "@/lib/api";

export const PLATFORM_TENANT_ADMIN_CAPABILITY = "platform.tenant.admin";

export function hasPlatformAdmin(principal: AuthPrincipal | null): boolean {
  return Boolean(
    principal?.capabilities?.includes(PLATFORM_TENANT_ADMIN_CAPABILITY)
  );
}

export type PlatformAccessState =
  | "loading"
  | "unauthenticated"
  | "refused"
  | "authorized"
  | "error";

export type PlatformAccessInput = {
  principal: AuthPrincipal | null;
  error: string | null;
  isLoading: boolean;
};

/**
 * Resolve what the app should render from the /auth/me result:
 *   - loading         — still resolving the principal
 *   - unauthenticated — no session / token (the principal read 401'd)
 *   - error           — the principal read failed for another reason
 *   - refused         — authenticated but WITHOUT platform.tenant.admin
 *   - authorized      — platform admin; render the platform shell
 *
 * Only `authorized` may render platform content.
 */
export function resolvePlatformAccess(
  input: PlatformAccessInput
): PlatformAccessState {
  if (input.isLoading) return "loading";
  if (input.error) {
    return isUnauthenticatedError(input.error) ? "unauthenticated" : "error";
  }
  if (!input.principal) return "unauthenticated";
  if (input.principal.authority_source !== "verified") return "unauthenticated";
  return hasPlatformAdmin(input.principal) ? "authorized" : "refused";
}

function isUnauthenticatedError(error: string): boolean {
  return /\b401\b/.test(error) || /unauthor/i.test(error) || /token/i.test(error);
}
