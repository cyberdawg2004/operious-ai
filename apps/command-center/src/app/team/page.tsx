'use client';

import { Plus } from 'lucide-react';
import { PageHeader } from '@/components/layout/page-header';
import { AwaitingBackend } from '@/components/ui/awaiting-backend';
import { cn } from '@/lib/cn';

export default function TeamRolesPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumb={['Workspace', 'Team & Roles']}
        title="Team & Roles"
        actions={
          <button
            type="button"
            disabled
            className={cn(
              'flex h-8 items-center gap-1.5 rounded-sm border border-line bg-bg-inset px-3',
              'font-mono text-2xs uppercase tracking-wider text-fg-dim opacity-60',
            )}
          >
            <Plus className="h-3.5 w-3.5" />
            Invite operator
          </button>
        }
      />
      <AwaitingBackend
        endpoint="GET tenant.members"
        description="Principals and role assignments are managed by the upstream identity provider (Auth0). The command-center directory will hydrate from the `tenant.members` endpoint once the backend exposes it. Until then, role changes are made through the IdP console."
      />
    </div>
  );
}
