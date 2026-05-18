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
        baseUrl: 'https://operious.local',
        // Mock fetch — replace with `globalThis.fetch` once the backend is exposed.
        fetch: mockFetch,
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
