'use client';

import { useState, type ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { UserProvider } from '@auth0/nextjs-auth0/client';
import { Toaster } from 'sonner';
import { OperiousClient, OperiousClientProvider } from '@operious/sdk';
import { AuthProvider, type AuthPrincipal } from '@operious/auth';
import { brand } from '@operious/shared';
import { SessionBridge } from '@/lib/auth0-bridge';
import { RightPanelProvider } from '@/components/layout/right-panel';
import { CommandPaletteProvider } from '@/components/command-palette/command-palette';
import { KeyboardShortcutProvider } from '@/components/keyboard/keyboard-provider';
import { env } from '@/lib/env';

interface ProvidersProps {
  readonly children: ReactNode;
}

/**
 * Dev-only mock identity gate.
 *
 * This is the single doctrine-approved site for the literal demo
 * principal / demo token. The constitutional invariant in
 * `tests-frontend/src/demo-identity-isolation.test.ts` pins these
 * literals to this file and forbids them anywhere else in the
 * command-center source tree.
 *
 * Production builds NEVER take this branch \u2014 USE_MOCK_API is false
 * unless `NEXT_PUBLIC_USE_MOCK_API=1` is explicitly set, which is
 * only ever done in a local dev shell to bypass Auth0.
 */
const USE_MOCK_API = env.useMockApi;

const buildDemoPrincipal = (): AuthPrincipal => ({
  principalId: brand<'PrincipalId'>('principal-demo'),
  tenantId: brand<'TenantId'>('tenant-demo'),
  displayName: 'Demo Operator',
  email: 'demo@operious.local',
  roles: ['operations:read', 'cognition:read', 'tenant:read'],
});

/**
 * Composed providers \u2014 the order matters:
 *
 *   QueryClient
 *     UserProvider (Auth0 client cookie)
 *       OperiousClient (SDK transport)
 *         AuthProvider (mock branch) | SessionBridge (Auth0 branch)
 *           RightPanel + CommandPalette + Keyboard
 *             <children />
 *           Toast slot
 *
 * Transport routing:
 *   \u2022 Auth0 configured  \u2192 SDK uses same-origin `/api/proxy` so the access
 *                          token never touches the browser.
 *   \u2022 Auth0 unconfigured \u2192 SDK targets the backend directly; the backend
 *                          will return 401 envelopes which the UI renders
 *                          inline. No mock fallback unless USE_MOCK_API is
 *                          explicitly set.
 */
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
          mutations: { retry: false },
        },
      }),
  );

  const [client] = useState(() => {
    const baseUrl = env.auth0Configured
      ? (typeof window !== 'undefined' ? window.location.origin : '') +
        '/api/proxy'
      : env.apiBaseUrl;
    return new OperiousClient({ baseUrl });
  });

  const demoPrincipal: AuthPrincipal | null = USE_MOCK_API
    ? buildDemoPrincipal()
    : null;
  const demoToken: string | null = USE_MOCK_API ? 'demo-token' : null;

  const Toast = (
    <Toaster
      theme="light"
      position="bottom-right"
      richColors
      closeButton
      toastOptions={{
        classNames: {
          toast:
            'bg-bg-inset border border-line text-fg shadow-raised font-sans',
          description: 'text-fg-muted',
          title: 'font-mono text-2xs uppercase tracking-wider',
        },
      }}
    />
  );

  const Body = (
    <RightPanelProvider>
      <CommandPaletteProvider>
        <KeyboardShortcutProvider>{children}</KeyboardShortcutProvider>
      </CommandPaletteProvider>
    </RightPanelProvider>
  );

  return (
    <QueryClientProvider client={queryClient}>
      <UserProvider>
        <OperiousClientProvider client={client}>
          {USE_MOCK_API ? (
            <AuthProvider principal={demoPrincipal} token={demoToken}>
              {Body}
              {Toast}
            </AuthProvider>
          ) : (
            <SessionBridge>
              {Body}
              {Toast}
            </SessionBridge>
          )}
        </OperiousClientProvider>
      </UserProvider>
    </QueryClientProvider>
  );
};
