/**
 * Auth0 route handler — `/api/auth/[auth0]`.
 *
 * Delegates to `@auth0/nextjs-auth0`'s `handleAuth` which auto-wires:
 *   - `/api/auth/login`     \u2192 begin OAuth2 redirect to Auth0
 *   - `/api/auth/callback`  \u2192 exchange code for session cookie
 *   - `/api/auth/logout`    \u2192 destroy session, redirect to Auth0 logout
 *   - `/api/auth/me`        \u2192 (Auth0 client cache; we DO NOT use this for
 *                            principal identity \u2014 the backend
 *                            `ENDPOINT.auth.me` is canonical)
 *
 * If Auth0 is not configured (env vars missing), every endpoint returns a
 * stable 503 envelope rather than crashing on startup. The UI surfaces this
 * via the top notification strip.
 */

import { NextResponse, type NextRequest } from 'next/server';
import { env } from '@/lib/env';

export const dynamic = 'force-dynamic';

const notConfiguredResponse = () =>
  NextResponse.json(
    {
      code: 'auth0_not_configured',
      message:
        'Auth0 env vars (AUTH0_SECRET, AUTH0_BASE_URL, AUTH0_ISSUER_BASE_URL, AUTH0_CLIENT_ID, AUTH0_CLIENT_SECRET) are not set in this environment.',
    },
    { status: 503 },
  );

const buildHandler = async () => {
  if (!env.auth0Configured) return null;
  const mod = await import('@auth0/nextjs-auth0');
  return mod.handleAuth();
};

export async function GET(
  request: NextRequest,
  context: { params: { auth0: string } },
) {
  const handler = await buildHandler();
  if (!handler) return notConfiguredResponse();
  return handler(request, context);
}

export async function POST(
  request: NextRequest,
  context: { params: { auth0: string } },
) {
  const handler = await buildHandler();
  if (!handler) return notConfiguredResponse();
  return handler(request, context);
}
