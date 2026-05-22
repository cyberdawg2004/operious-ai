'use client';

import { useSession } from '@/lib/auth0-bridge';
import { PageHeader } from '@/components/layout/page-header';
import { AwaitingBackend } from '@/components/ui/awaiting-backend';
import { StatusPill } from '@/components/ui/status-pill';
import { env } from '@/lib/env';

export default function SettingsPage() {
  const session = useSession();
  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumb={['Workspace', 'Settings']}
        title="Settings"
      />

      <section className="rounded-md border border-line bg-bg-inset p-5 shadow-card">
        <p className="mb-3 text-mono text-fg-dim">session</p>
        <dl className="grid grid-cols-3 gap-2 text-mono text-fg-subtle">
          <DT>Environment</DT>
          <DD className="col-span-2">{env.environmentLabel}</DD>
          <DT>Auth0 configured</DT>
          <DD className="col-span-2">
            <StatusPill tone={env.auth0Configured ? 'active' : 'denied'}>
              {env.auth0Configured ? 'yes' : 'no'}
            </StatusPill>
          </DD>
          <DT>Authenticated</DT>
          <DD className="col-span-2">
            <StatusPill tone={session.isAuthenticated ? 'active' : 'neutral'}>
              {session.isAuthenticated ? 'yes' : 'no'}
            </StatusPill>
          </DD>
          {session.principal ? (
            <>
              <DT>Principal</DT>
              <DD className="col-span-2 truncate">
                {session.principal.principalId as unknown as string}
              </DD>
              <DT>Tenant</DT>
              <DD className="col-span-2 truncate">
                {(session.principal.tenantId as unknown as string) ?? '\u2014'}
              </DD>
              <DT>Capabilities</DT>
              <DD className="col-span-2 truncate">
                {session.principal.roles.join(', ') || '\u2014'}
              </DD>
            </>
          ) : null}
          <DT>API base URL</DT>
          <DD className="col-span-2 break-all">{env.apiBaseUrl}</DD>
        </dl>
      </section>

      <AwaitingBackend
        endpoint="GET tenant.settings"
        description="Workspace preferences (timezone, notification policy, redaction strictness) will surface here once the backend exposes the settings endpoint. Auth0 profile changes are handled in the Auth0 dashboard."
      />
    </div>
  );
}

const DT = ({ children }: { children: React.ReactNode }) => (
  <dt className="text-fg-dim">{children}</dt>
);
const DD = ({
  children,
  className = '',
}: {
  children: React.ReactNode;
  className?: string;
}) => <dd className={`text-fg-muted ${className}`}>{children}</dd>;
