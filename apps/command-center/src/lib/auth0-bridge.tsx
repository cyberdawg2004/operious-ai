'use client';

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  type ReactNode,
} from 'react';
import { useUser } from '@auth0/nextjs-auth0/client';
import { useQuery } from '@tanstack/react-query';
import { useAuthedRequest } from '@operious/sdk';
import { ENDPOINT } from '@operious/contracts';
import type { MePrincipalDto } from '@operious/types';
import { isErr, brand } from '@operious/shared';
import { AuthProvider, type AuthPrincipal } from '@operious/auth';
import { env } from '@/lib/env';

/**
 * Auth0 bridge \u2014 converts the Auth0 session cookie + verified backend
 * `auth.me` response into a single `AuthPrincipal` value that the SDK's
 * `useAuth` reads.
 *
 * Authority order:
 *   1. Auth0 session presence (cookie verified by middleware)
 *   2. Bearer token forwarding (we attach the `Authorization: Bearer ...`
 *      header the Auth0 SDK exposes \u2014 in the typical Auth0 SPA pattern the
 *      session cookie itself is the credential and we forward it via
 *      `credentials: 'include'`; only when a custom `accessToken` cookie is
 *      present do we attach the Authorization header)
 *   3. Backend `ENDPOINT.auth.me` returns the canonical `AuthorityContext`
 *      \u2014 we trust this over any client-side claim.
 *
 * `displayName` and `email` come from the Auth0 user object (presentational
 * only). The backend never trusts these for authorization.
 */

interface SessionContextValue {
  readonly isLoading: boolean;
  readonly isAuth0Configured: boolean;
  readonly isAuthenticated: boolean;
  readonly principal: AuthPrincipal | null;
  readonly me: MePrincipalDto | null;
  readonly error: string | null;
}

const SessionContext = createContext<SessionContextValue>({
  isLoading: false,
  isAuth0Configured: false,
  isAuthenticated: false,
  principal: null,
  me: null,
  error: null,
});

export const useSession = () => useContext(SessionContext);

const buildPrincipal = (
  me: MePrincipalDto,
  displayName: string,
  email: string | undefined,
): AuthPrincipal => ({
  principalId: me.principalId ?? brand<'PrincipalId'>('unknown'),
  tenantId: me.tenantId,
  displayName,
  email,
  roles: [...me.capabilities],
});

interface BridgeProps {
  readonly children: ReactNode;
  readonly isAuth0Configured: boolean;
}

/**
 * Inner bridge \u2014 already inside the SDK's request context but NOT inside
 * the AuthProvider. Computes the principal and hands it to AuthProvider
 * which the SDK then reads via `useAuthHeader`.
 */
const SessionBridgeInner = ({ children, isAuth0Configured }: BridgeProps) => {
  const { user, isLoading: auth0Loading, error: auth0Error } = useUser();
  const request = useAuthedRequest();

  // Only fetch /me when the user is authenticated. When Auth0 is unconfigured
  // we still allow the page to render (operator sees the banner).
  const meQuery = useQuery<MePrincipalDto>({
    queryKey: ['auth-me'],
    enabled: isAuth0Configured && Boolean(user),
    staleTime: 30_000,
    retry: false,
    queryFn: async () => {
      const envelope = await request<MePrincipalDto>(ENDPOINT.auth.me);
      const result = envelope.result;
      if (isErr(result)) {
        const reason =
          result.error instanceof Error
            ? result.error.message
            : typeof result.error === 'object' &&
                result.error !== null &&
                'message' in result.error
              ? String((result.error as { message: unknown }).message)
              : 'auth.me failed';
        throw new Error(reason);
      }
      return result.value;
    },
  });

  const value = useMemo<SessionContextValue>(() => {
    if (!isAuth0Configured) {
      return {
        isLoading: false,
        isAuth0Configured: false,
        isAuthenticated: false,
        principal: null,
        me: null,
        error: null,
      };
    }
    if (auth0Loading || meQuery.isLoading) {
      return {
        isLoading: true,
        isAuth0Configured: true,
        isAuthenticated: false,
        principal: null,
        me: null,
        error: null,
      };
    }
    if (auth0Error) {
      return {
        isLoading: false,
        isAuth0Configured: true,
        isAuthenticated: false,
        principal: null,
        me: null,
        error: auth0Error.message,
      };
    }
    if (!user) {
      return {
        isLoading: false,
        isAuth0Configured: true,
        isAuthenticated: false,
        principal: null,
        me: null,
        error: null,
      };
    }
    if (meQuery.error) {
      return {
        isLoading: false,
        isAuth0Configured: true,
        isAuthenticated: false,
        principal: null,
        me: null,
        error: meQuery.error.message,
      };
    }
    if (!meQuery.data) {
      return {
        isLoading: false,
        isAuth0Configured: true,
        isAuthenticated: false,
        principal: null,
        me: null,
        error: null,
      };
    }
    return {
      isLoading: false,
      isAuth0Configured: true,
      isAuthenticated: true,
      principal: buildPrincipal(
        meQuery.data,
        (user.name as string | undefined) ?? user.email ?? 'Operator',
        user.email ?? undefined,
      ),
      me: meQuery.data,
      error: null,
    };
  }, [
    isAuth0Configured,
    auth0Loading,
    auth0Error,
    user,
    meQuery.isLoading,
    meQuery.error,
    meQuery.data,
  ]);

  return (
    <SessionContext.Provider value={value}>
      <AuthProvider principal={value.principal} token={null}>
        {children}
      </AuthProvider>
    </SessionContext.Provider>
  );
};

interface OuterProps {
  readonly children: ReactNode;
}

/**
 * Outer bridge \u2014 reads from the `<UserProvider>` mounted higher and
 * exposes a single composed context. Components throughout the app read
 * `useSession()` for principal + auth state.
 */
export const SessionBridge = ({ children }: OuterProps) => (
  <SessionBridgeInner isAuth0Configured={env.auth0Configured}>
    {children}
  </SessionBridgeInner>
);

/**
 * Helper hook \u2014 the canonical principal (or `null` if not authenticated).
 * Use this from page-level UI; component-level UI should prefer
 * `useAuth()` from `@operious/auth` so it remains framework-agnostic.
 */
export const usePrincipal = (): AuthPrincipal | null => useSession().principal;

/**
 * Effect bootstrap \u2014 invalidate `/me` cache when the Auth0 user changes.
 */
export const useMeReconciler = (): void => {
  const { user } = useUser();
  const sub = (user as { sub?: string } | undefined)?.sub;
  useEffect(() => {
    // The query is keyed on `['auth-me']`; TanStack will refetch on enable
    // toggling. No manual invalidation is required \u2014 this hook is kept as
    // a deliberate seam so future logic (e.g. tenant-switch token refresh)
    // can hang off the same observer.
    void sub;
  }, [sub]);
};
