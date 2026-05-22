/**
 * Auth-bearing reverse proxy \u2014 `/api/proxy/<backend path>`.
 *
 * Why this exists
 * \u2014\u2014\u2014\u2014\u2014\u2014\u2014\u2014\u2014
 * The browser SDK MUST attach a verified Bearer token to every backend
 * request. There are two ways to do that:
 *
 *   1. Expose the Auth0 access token to JS via `/api/auth/me` and let the
 *      SDK attach it client-side. This leaks the token to the browser
 *      runtime \u2014 a security regression in an enterprise operator surface.
 *
 *   2. Keep the token server-side. The SDK calls a same-origin proxy,
 *      the proxy reads the Auth0 session via `getAccessToken()`, attaches
 *      the Bearer header, and forwards the request to the backend.
 *
 * We pick (2). The Auth0 access token never touches the browser. The proxy
 * is intentionally a pure transport \u2014 it adds NO operational semantics,
 * NO retries, NO body mutation. The backend remains the sole source of
 * truth and the backend authority middleware sees the canonical token.
 *
 * Pass-through rules:
 *   - Forwards method, headers (minus `host`), body, query string
 *   - Attaches `Authorization: Bearer <access_token>` when a session exists
 *   - Returns the upstream response verbatim (status + body + headers)
 *   - NEVER caches \u2014 every call is fresh
 */

import { NextResponse, type NextRequest } from 'next/server';
import { env } from '@/lib/env';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const HOP_BY_HOP = new Set([
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailer',
  'transfer-encoding',
  'upgrade',
  'host',
  'content-length',
]);

const forwardableHeaders = (request: NextRequest): Headers => {
  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) headers.set(key, value);
  });
  return headers;
};

const resolveAccessToken = async (
  request: NextRequest,
): Promise<string | null> => {
  if (!env.auth0Configured) return null;
  try {
    const mod = await import('@auth0/nextjs-auth0');
    // `getAccessToken` is typed for the pages router (NextApiRequest /
    // NextApiResponse) but works in app-router contexts when passed the
    // app-router Request + a fresh NextResponse. We cast to `unknown`
    // first so TS does not complain about the narrow public typing.
    const args = [
      request,
      NextResponse.next(),
    ] as unknown as Parameters<typeof mod.getAccessToken>;
    const result = await mod.getAccessToken(...args);
    return result.accessToken ?? null;
  } catch {
    return null;
  }
};

const handler = async (
  request: NextRequest,
  { params }: { params: { path: string[] } },
): Promise<Response> => {
  const upstreamBase = env.apiBaseUrl.replace(/\/$/, '');
  const upstreamPath = `/${(params.path ?? []).join('/')}`;
  const url = new URL(upstreamPath, upstreamBase);
  request.nextUrl.searchParams.forEach((value, key) =>
    url.searchParams.set(key, value),
  );

  const headers = forwardableHeaders(request);
  const token = await resolveAccessToken(request);
  if (token) headers.set('authorization', `Bearer ${token}`);

  const init: RequestInit = {
    method: request.method,
    headers,
    redirect: 'manual',
  };
  if (!['GET', 'HEAD'].includes(request.method)) {
    init.body = await request.arrayBuffer();
  }

  try {
    const upstream = await fetch(url.toString(), init);
    const buffer = await upstream.arrayBuffer();
    const responseHeaders = new Headers();
    upstream.headers.forEach((value, key) => {
      if (!HOP_BY_HOP.has(key.toLowerCase())) {
        responseHeaders.set(key, value);
      }
    });
    return new NextResponse(buffer, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: responseHeaders,
    });
  } catch (cause) {
    return NextResponse.json(
      {
        code: 'proxy_transport_error',
        message:
          cause instanceof Error
            ? cause.message
            : 'upstream backend unreachable',
        substrate: 'sdk',
      },
      { status: 502 },
    );
  }
};

export { handler as GET, handler as POST, handler as PUT, handler as PATCH, handler as DELETE };
