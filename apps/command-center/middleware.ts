import { NextResponse, type NextRequest } from 'next/server';

/**
 * Edge middleware \u2014 session enforcement.
 *
 * When Auth0 is configured we delegate to `withMiddlewareAuthRequired` so
 * every page route requires a valid session before render. When Auth0 is
 * NOT configured we pass requests through unchanged so the app can boot
 * into its "Auth0 not configured" banner instead of an infinite redirect
 * loop \u2014 the operator can still see the shell.
 *
 * The matcher excludes:
 *   - the Auth0 handler itself (would deadlock the login redirect)
 *   - Next.js internals (`/_next/*`)
 *   - static assets
 *   - the favicon
 */

const auth0Configured = Boolean(
  process.env.AUTH0_SECRET &&
    process.env.AUTH0_BASE_URL &&
    process.env.AUTH0_ISSUER_BASE_URL &&
    process.env.AUTH0_CLIENT_ID &&
    process.env.AUTH0_CLIENT_SECRET,
);

export async function middleware(request: NextRequest) {
  if (!auth0Configured) return NextResponse.next();
  // Lazy import keeps the unconfigured boot path light.
  const { withMiddlewareAuthRequired } = await import(
    '@auth0/nextjs-auth0/edge'
  );
  const handler = withMiddlewareAuthRequired();
  return handler(request);
}

export const config = {
  matcher: [
    /*
     * Match all request paths except:
     *   - /api/auth/*           (Auth0 handler)
     *   - /_next/static/*       (static bundle)
     *   - /_next/image/*        (Next.js image optimizer)
     *   - /favicon.ico, /robots.txt
     *   - any file ending in a common static extension
     */
    '/((?!api/auth|_next/static|_next/image|favicon.ico|robots.txt|.*\\..*).*)',
  ],
};
