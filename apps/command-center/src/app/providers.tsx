'use client';

import { useState, type ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider, buildPrincipal, type AuthPrincipal } from '@operious/auth';
import { OperiousClient, OperiousClientProvider } from '@operious/sdk';
import { LocaleProvider } from '@/locale/provider';
import { mockFetch } from '@/mocks/fetch';

interface ProvidersProps {
  readonly children: ReactNode;
}

/**
 * Frontend authority singularity (Core Law 1): the frontend is purely
 * representational and MUST NOT produce operational truth. `mockFetch`
 * synthesises backend-shaped responses from local fixtures — useful
 * for development, but if it slipped into production the frontend
 * would be producing the operational truth that only the backend may
 * own. Gating below makes the dev-mock path explicit and grep-able;
 * production builds default to the platform-native transport
 * inside OperiousClient (no mock interception).
 */
const USE_MOCK_API =
  process.env.NEXT_PUBLIC_OPERIOUS_USE_MOCK_API === 'true';

/**
 * 2.5-J2: the demo principal / token used to be unconditionally
 * injected at every render — meaning a production build would
 * carry ``principal-demo`` / ``demo-token`` to the backend. The
 * backend's trusted-ingress middleware would (correctly) reject
 * these, but the frontend should never *produce* them in the first
 * place. The demo principal is now strictly gated to the same
 * dev-mock flag as the mock fetch transport. In production the
 * principal/token are ``null`` until a real auth flow hydrates
 * them; the SDK will treat the request as anonymous (matching the
 * doctrine in ``packages/auth/src/context.tsx::useAuthHeader``).
 */
const buildDemoPrincipal = (): AuthPrincipal =>
  buildPrincipal({
    principalId: 'principal-demo',
    tenantId: 'tenant-acme',
    displayName: 'Operations Operator',
    email: 'ops@operious.local',
    roles: ['operations.read', 'cognition.review'],
  });

export const Providers = ({ children }: ProvidersProps) => {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: false,
            refetchOnWindowFocus: false,
            staleTime: 30_000,
          },
          mutations: {
            retry: false,
          },
        },
      }),
  );

  const [client] = useState(
    () =>
      new OperiousClient({
        baseUrl:
          process.env.NEXT_PUBLIC_OPERIOUS_API_BASE_URL ??
          'https://operious.local',
        // `mockFetch` is dev-only and feature-gated. When the flag is
        // off (the production default) OperiousClient falls back to
        // its built-in platform transport, and the backend is the
        // only source of operational truth.
        fetch: USE_MOCK_API ? mockFetch : undefined,
      }),
  );

  // 2.5-J2: principal + token are ONLY injected in dev-mock mode.
  // Production hydration is the responsibility of a future signed-
  // session bootstrap; until then the SDK treats the request as
  // anonymous and the backend rejects non-public endpoints.
  const principal: AuthPrincipal | null = USE_MOCK_API
    ? buildDemoPrincipal()
    : null;
  const token: string | null = USE_MOCK_API ? 'demo-token' : null;

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider principal={principal} token={token}>
        <OperiousClientProvider client={client}>
          <LocaleProvider initialLocale="en">{children}</LocaleProvider>
        </OperiousClientProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
};
