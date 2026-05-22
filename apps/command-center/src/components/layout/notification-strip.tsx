'use client';

import { useSession } from '@/lib/auth0-bridge';
import { env } from '@/lib/env';

/**
 * Top notification strip \u2014 a thin gold bar that surfaces operational state.
 *
 * Today it announces:
 *   \u2022 "Auth0 not configured" \u2014 if env vars are missing
 *   \u2022 "Backend unreachable" or other principal/session errors
 *
 * It is intentionally restrained \u2014 a single line, no animation, never
 * dismissible (the message goes away when the underlying condition does).
 */
export const NotificationStrip = () => {
  const { isAuth0Configured, isAuthenticated, error } = useSession();

  if (!isAuth0Configured) {
    return (
      <div className="bg-accent/15 border-b border-accent/40 px-6 py-1.5 text-mono text-fg-muted">
        <span className="mr-2 inline-block h-1.5 w-1.5 rounded-full bg-accent" />
        Auth0 is not configured in this environment ({env.environmentLabel}). Set
        AUTH0_SECRET, AUTH0_BASE_URL, AUTH0_ISSUER_BASE_URL, AUTH0_CLIENT_ID,
        AUTH0_CLIENT_SECRET to enable session enforcement.
      </div>
    );
  }

  if (isAuth0Configured && !isAuthenticated && error) {
    return (
      <div className="bg-signal-deny/10 border-b border-signal-deny/40 px-6 py-1.5 text-mono text-signal-deny">
        <span className="mr-2 inline-block h-1.5 w-1.5 rounded-full bg-signal-deny" />
        Session error: {error}
      </div>
    );
  }

  return null;
};
