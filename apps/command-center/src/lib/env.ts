/**
 * Environment shim.
 *
 * Centralises every NEXT_PUBLIC_* and server-only env var the command-center
 * touches. Keeps env-name typos out of components and surfaces missing
 * configuration up-front so the app boots into a banner state instead of
 * crashing with a generic SDK error mid-render.
 */

export const env = {
  /** Backend base URL — the SDK targets this for every API call. */
  apiBaseUrl:
    process.env.NEXT_PUBLIC_OPERIOUS_API_BASE_URL ??
    process.env.NEXT_PUBLIC_OPERIOUS_API_URL ??
    'https://operious-ai-imad.fly.dev',

  /** Whether Auth0 is fully configured in this environment. */
  auth0Configured: Boolean(
    process.env.AUTH0_SECRET &&
      process.env.AUTH0_BASE_URL &&
      process.env.AUTH0_ISSUER_BASE_URL &&
      process.env.AUTH0_CLIENT_ID &&
      process.env.AUTH0_CLIENT_SECRET,
  ),

  /** Build/runtime indicator the UI surfaces in the notification strip. */
  environmentLabel:
    process.env.NEXT_PUBLIC_OPERIOUS_ENV_LABEL ?? 'production',

  /**
   * Dev-only mock identity gate. When `NEXT_PUBLIC_USE_MOCK_API=1`, the
   * command-center skips the Auth0 round-trip and injects a deterministic
   * demo principal so a local dev server can exercise the UI without
   * touching Auth0. Never enable this in production \u2014 the gate exists
   * solely to keep the dev loop frictionless; the production path always
   * runs through Auth0 + `ENDPOINT.auth.me`.
   */
  useMockApi:
    process.env.NEXT_PUBLIC_USE_MOCK_API === '1' ||
    process.env.NEXT_PUBLIC_USE_MOCK_API === 'true',
};
