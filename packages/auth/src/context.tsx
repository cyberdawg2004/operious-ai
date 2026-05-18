'use client';

import { createContext, useContext, useMemo, type ReactNode } from 'react';
import type { PrincipalId, TenantId } from '@operious/types';
import { brand } from '@operious/shared';

/**
 * Read-only principal envelope. The frontend never derives this — it is
 * provided externally (env, server-component prop, or future auth provider).
 *
 * `displayName` and `email` are PRESENTATIONAL fields. They have no operational
 * authority and the backend does not trust them for authorization.
 */
export interface AuthPrincipal {
  readonly principalId: PrincipalId;
  readonly tenantId?: TenantId;
  readonly displayName: string;
  readonly email?: string;
  readonly roles: readonly string[];
}

export interface AuthContextValue {
  readonly principal: AuthPrincipal | null;
  readonly token: string | null;
}

const AuthContext = createContext<AuthContextValue>({ principal: null, token: null });

interface AuthProviderProps {
  readonly principal?: AuthPrincipal | null;
  readonly token?: string | null;
  readonly children: ReactNode;
}

export const AuthProvider = ({
  principal = null,
  token = null,
  children,
}: AuthProviderProps) => {
  const value = useMemo<AuthContextValue>(() => ({ principal, token }), [principal, token]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = (): AuthContextValue => useContext(AuthContext);

/**
 * Returns the auth header tuple SDK fetch wrappers will attach.
 * If no token is present, no header is attached and the backend will treat
 * the request as anonymous — and reject it for any non-public endpoint.
 *
 * The frontend NEVER fabricates a principal-id header without a token.
 */
export const useAuthHeader = (): Readonly<Record<string, string>> => {
  const { token } = useAuth();
  return useMemo<Readonly<Record<string, string>>>(() => {
    const headers: Record<string, string> = {};
    if (token) headers.Authorization = `Bearer ${token}`;
    return headers;
  }, [token]);
};

/**
 * Helper for tests / dev seeds — never call in production code paths.
 * The brand cast funnels raw strings through `@operious/shared`.
 */
export const buildPrincipal = (input: {
  principalId: string;
  tenantId?: string;
  displayName: string;
  email?: string;
  roles?: readonly string[];
}): AuthPrincipal => ({
  principalId: brand<'PrincipalId'>(input.principalId),
  tenantId: input.tenantId ? brand<'TenantId'>(input.tenantId) : undefined,
  displayName: input.displayName,
  email: input.email,
  roles: input.roles ?? [],
});
