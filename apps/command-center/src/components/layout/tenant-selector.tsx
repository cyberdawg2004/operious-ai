'use client';

import { useEffect, useRef, useState } from 'react';
import { ChevronDown, Check, Building2 } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { useTenantStore, tenant } from '@/lib/tenant-store';
import { useSession } from '@/lib/auth0-bridge';
import { cn } from '@/lib/cn';
import { TENANT_CEREMONY } from '@/lib/motion';
import { TenantCeremony } from './tenant-ceremony';

/**
 * Tenant selector.
 *
 * Reads the authorised tenant set from the backend `/me` response (single
 * tenant axis today; the backend will extend this to a tenant list claim
 * as soon as the multi-tenant identity model lands). Switching tenants
 * clears the entire query cache so stale tenant-A artifacts cannot bleed
 * into the tenant-B render \u2014 the tenant-isolation acceptance criterion.
 */
export const TenantSelector = () => {
  const { me } = useSession();
  const { currentTenantId, availableTenantIds, setAvailable, setCurrent } =
    useTenantStore();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [ceremony, setCeremony] = useState<{ active: boolean; name: string }>({
    active: false,
    name: '',
  });
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (me?.tenantId) {
      setAvailable([me.tenantId]);
    }
  }, [me?.tenantId, setAvailable]);

  useEffect(() => {
    if (!open) return;
    const handler = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const tenantLabel = currentTenantId
    ? (currentTenantId as unknown as string)
    : me?.tenantId
      ? (me.tenantId as unknown as string)
      : 'No tenant';

  const handleSwitch = (id: string) => {
    const next = tenant(id);
    setOpen(false);
    // Tenant isolation — every cached read must be re-fetched against the
    // new tenant axis. The query cache is wiped wholesale. The ceremony
    // overlay marks the moment so operators register that they are now
    // looking at a different sovereign environment.
    setCeremony({ active: true, name: id });
    setCurrent(next);
    queryClient.clear();
    // Hold the ceremony just long enough for the seal rotation to land,
    // then dismiss so the new context is visible.
    window.setTimeout(
      () => setCeremony({ active: false, name: id }),
      TENANT_CEREMONY.sealRotateMs + TENANT_CEREMONY.contentInMs + 80,
    );
  };

  if (availableTenantIds.length === 0 && !me?.tenantId) {
    return (
      <div className="rounded-sm border border-line bg-bg px-2.5 py-2 text-mono text-fg-dim">
        <Building2 className="inline h-3 w-3 mr-1.5" />
        no tenant axis
      </div>
    );
  }

  return (
    <>
    <TenantCeremony active={ceremony.active} tenantName={ceremony.name} />
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className={cn(
          'flex w-full items-center justify-between gap-2',
          'rounded-sm border border-line bg-bg px-2.5 py-2',
          'text-left transition-colors hover:border-line-strong hover:bg-bg-raised',
        )}
      >
        <div className="min-w-0 flex-1">
          <p className="text-mono text-fg-dim">tenant</p>
          <p className="truncate font-mono text-xs text-fg">{tenantLabel}</p>
        </div>
        <ChevronDown
          className={cn(
            'h-4 w-4 text-fg-subtle transition-transform',
            open && 'rotate-180',
          )}
        />
      </button>
      {open ? (
        <div
          role="listbox"
          className={cn(
            'absolute left-0 right-0 top-full z-40 mt-1',
            'rounded-md border border-line bg-bg-inset shadow-raised',
            'animate-fade-in py-1',
          )}
        >
          {availableTenantIds.map((id) => {
            const label = id as unknown as string;
            const active = label === tenantLabel;
            return (
              <button
                key={label}
                type="button"
                role="option"
                aria-selected={active}
                onClick={() => handleSwitch(label)}
                className={cn(
                  'flex w-full items-center gap-2 px-2.5 py-1.5',
                  'text-left font-mono text-xs transition-colors',
                  active
                    ? 'bg-bg-raised text-fg'
                    : 'text-fg-muted hover:bg-bg-raised hover:text-fg',
                )}
              >
                {active ? (
                  <Check className="h-3 w-3 text-accent" />
                ) : (
                  <span className="w-3" />
                )}
                <span className="truncate">{label}</span>
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
    </>
  );
};
