'use client';

import { Download } from 'lucide-react';
import { PageHeader } from '@/components/layout/page-header';
import { AwaitingBackend } from '@/components/ui/awaiting-backend';
import { cn } from '@/lib/cn';

export default function AuditExportsPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumb={['Compliance', 'Audit & Exports']}
        title="Audit & Exports"
        actions={
          <button
            type="button"
            disabled
            className={cn(
              'flex h-8 items-center gap-1.5 rounded-sm border border-line bg-bg-inset px-3',
              'font-mono text-2xs uppercase tracking-wider text-fg-dim opacity-60',
            )}
          >
            <Download className="h-3.5 w-3.5" />
            Generate Export
          </button>
        }
      />
      <AwaitingBackend
        endpoint="GET audit.exports"
        description="Signed forensic bundles and the audit activity log will surface here once the backend exposes the audit-export endpoints. Until then, exports can be requested via the Trace Inspector (Export forensic bundle, per-correlation) which streams the raw bundle as a signed JSON."
      />
    </div>
  );
}
