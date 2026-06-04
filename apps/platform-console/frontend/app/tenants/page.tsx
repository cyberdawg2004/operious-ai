"use client";

import { useCallback } from "react";
import { Building2, Loader2 } from "lucide-react";
import { listTenantLifecycle, type TenantLifecycleRecord } from "@/lib/api";
import { useApiResource } from "@/lib/use-api-resource";
import { PlatformConsole } from "@/components/platform-console";

export default function TenantsPage() {
  return (
    <PlatformConsole>
      <TenantsView />
    </PlatformConsole>
  );
}

/**
 * Placeholder landing. Proves auth + bearer + a platform-route call end to end:
 * an authenticated platform admin sees the tenant list. There is NO create flow
 * yet — that arrives with the onboarding move in the next spec.
 */
function TenantsView() {
  const load = useCallback(() => listTenantLifecycle(), []);
  const { data, error, isLoading, reload } = useApiResource(load);
  const tenants = data?.items ?? [];

  return (
    <main className="min-w-0 flex-1 overflow-auto bg-canvas p-4 sm:p-6 lg:p-8">
      <div className="eyebrow text-ink-tertiary mb-2">PLATFORM · TENANTS</div>
      <h1 className="mb-2 font-display text-[32px] font-semibold text-ink-primary">
        Tenants
      </h1>
      <p className="mb-5 max-w-2xl text-[13px] leading-relaxed text-ink-secondary">
        Tenant lifecycle records returned by the platform API. Onboarding (create
        and configure) arrives in the next release; this scaffold proves the
        platform-gated, bearer-authenticated read path works end to end.
      </p>

      {isLoading && (
        <div className="flex min-h-[160px] items-center justify-center rounded-lg border border-border-subtle bg-surface">
          <Loader2 className="h-4 w-4 animate-spin text-ink-tertiary" strokeWidth={1.8} />
        </div>
      )}

      {error && !isLoading && (
        <div className="rounded-lg border border-red-alert/30 bg-surface p-4 text-[13px] text-red-alert">
          <p className="font-semibold">Tenant list unavailable</p>
          <p className="mt-1 text-ink-secondary">{error}</p>
          <button
            type="button"
            onClick={reload}
            className="mt-3 inline-flex h-9 items-center rounded border border-border-subtle px-3 text-[12px] text-ink-secondary hover:border-border-defined hover:text-ink-primary"
          >
            Retry
          </button>
        </div>
      )}

      {!isLoading && !error && tenants.length === 0 && (
        <div className="rounded-lg border border-border-subtle bg-surface p-6 text-center">
          <Building2 className="mx-auto h-6 w-6 text-ink-tertiary" strokeWidth={1.6} />
          <p className="mt-3 text-[14px] font-semibold text-ink-primary">No tenants yet</p>
          <p className="mt-1 text-[13px] text-ink-secondary">
            The platform lifecycle endpoint returned no tenant records.
          </p>
        </div>
      )}

      {!isLoading && !error && tenants.length > 0 && (
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
          {tenants.map((tenant) => (
            <TenantCard key={tenant.tenant_id} tenant={tenant} />
          ))}
        </div>
      )}
    </main>
  );
}

function TenantCard({ tenant }: { tenant: TenantLifecycleRecord }) {
  return (
    <article className="rounded-lg border border-border-subtle bg-surface p-4">
      <div className="flex items-start justify-between gap-3">
        <h2 className="truncate text-[16px] font-semibold text-ink-primary">
          {tenant.tenant_id}
        </h2>
        <span className="shrink-0 rounded border border-border-subtle px-2 py-1 font-mono text-[10px] uppercase tracking-[0.12em] text-ink-tertiary">
          {tenant.status}
        </span>
      </div>
      <p className="mt-2 font-mono text-[11px] text-ink-tertiary">
        created {tenant.created_at}
      </p>
    </article>
  );
}
