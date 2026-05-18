'use client';

import { useState, type ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider, buildPrincipal } from '@operious/auth';
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

  const principal = buildPrincipal({
    principalId: 'principal-demo',
    tenantId: 'tenant-acme',
    displayName: 'Operations Operator',
    email: 'ops@operious.local',
    roles: ['operations.read', 'cognition.review'],
  });

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider principal={principal} token="demo-token">
        <OperiousClientProvider client={client}>
          <LocaleProvider initialLocale="en">{children}</LocaleProvider>
        </OperiousClientProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
};
