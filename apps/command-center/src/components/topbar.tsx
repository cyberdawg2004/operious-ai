'use client';

import { useAuth } from '@operious/auth';
import { Badge } from '@operious/ui';
import { useLocale } from '@/locale/provider';

export const Topbar = () => {
  const { principal } = useAuth();
  const { isRtl } = useLocale();
  return (
    <header
      dir={isRtl ? 'rtl' : 'ltr'}
      className="flex items-center justify-between border-b border-line bg-bg px-6 py-3"
    >
      <div className="flex items-center gap-3">
        <Badge tone="info">read-only inspection</Badge>
        <span className="text-mono text-fg-subtle">env: dev · mock backend</span>
      </div>
      {principal ? (
        <div className="flex items-center gap-3 text-mono text-fg-muted">
          <span>{principal.displayName}</span>
          <span className="text-fg-dim">{principal.tenantId as unknown as string}</span>
          <Badge tone="pending">pilot</Badge>
        </div>
      ) : null}
    </header>
  );
};
