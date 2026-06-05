"use client";

import { useCallback, useState } from "react";
import { ArrowRight, Building2, Check, ExternalLink, Lock } from "lucide-react";
import {
  ApiError,
  createTenantLifecycle,
  formatApiError,
  listTenantLifecycle,
  type TenantLifecycleRecord,
} from "@/lib/api";
import { describeTenantStatus } from "@/lib/tenant-status";
import { useApiResource } from "@/lib/use-api-resource";

const COMMAND_CENTER_URL =
  process.env.NEXT_PUBLIC_COMMAND_CENTER_URL || "https://app.operious.com";

/**
 * Phase A only. The Platform Console creates a tenant (a platform operation)
 * and hands off across the re-auth boundary. It does NOT — and cannot —
 * configure the tenant: the platform token is never scoped to the new tenant,
 * and the config editors live in the Command Center. Phase B happens there.
 */
export function TenantOnboarding() {
  const load = useCallback(() => listTenantLifecycle(), []);
  const { data, isLoading, error, reload } = useApiResource(load);
  const tenants = data?.items ?? [];

  const [selected, setSelected] = useState<TenantLifecycleRecord | null>(null);

  return (
    <main className="min-w-0 flex-1 overflow-auto bg-canvas p-4 sm:p-6 lg:p-8">
      <div className="eyebrow text-ink-tertiary mb-2">PLATFORM · ONBOARDING</div>
      <h1 className="mb-2 font-display text-[32px] font-semibold text-ink-primary">
        Onboard a Tenant
      </h1>
      <p className="mb-6 max-w-2xl text-[13px] leading-relaxed text-ink-secondary">
        Create a tenant (Phase A), then hand off across the tenant-isolation
        boundary. Configuration (Phase B) is done in the Command Center by a user
        scoped to the new tenant — it cannot be done from here.
      </p>

      <Step index={1} title="Create tenant">
        <CreateTenantForm
          existing={tenants}
          onCreated={(record) => {
            setSelected(record);
            reload();
          }}
        />
      </Step>

      <Step index={2} title="Re-auth handoff (tenant-isolation boundary)">
        {selected ? (
          <Handoff record={selected} />
        ) : (
          <p className="text-[13px] text-ink-tertiary">
            Create or select a tenant above to see its configuration handoff.
          </p>
        )}
      </Step>

      <section className="mt-6">
        <h2 className="mb-2 font-mono text-[11px] uppercase tracking-[0.14em] text-ink-tertiary">
          Existing tenants
        </h2>
        {isLoading && <p className="text-[13px] text-ink-tertiary">Loading tenants…</p>}
        {error && !isLoading && (
          <div className="rounded border border-red-alert/30 bg-surface p-3 text-[13px] text-red-alert">
            {error}
          </div>
        )}
        {!isLoading && !error && tenants.length === 0 && (
          <p className="text-[13px] text-ink-tertiary">No tenants yet.</p>
        )}
        {!isLoading && !error && tenants.length > 0 && (
          <div className="grid grid-cols-1 gap-2 xl:grid-cols-2">
            {tenants.map((tenant) => (
              <button
                key={tenant.tenant_id}
                type="button"
                onClick={() => setSelected(tenant)}
                className={`flex items-center justify-between gap-3 rounded-lg border bg-surface p-3 text-left transition-colors hover:border-border-defined ${
                  selected?.tenant_id === tenant.tenant_id
                    ? "border-gold-primary"
                    : "border-border-subtle"
                }`}
              >
                <span className="flex items-center gap-2 min-w-0">
                  <Building2 className="h-4 w-4 shrink-0 text-ink-tertiary" strokeWidth={1.8} />
                  <span className="truncate text-[14px] font-semibold text-ink-primary">
                    {tenant.tenant_id}
                  </span>
                </span>
                <span className="shrink-0 rounded border border-border-subtle px-2 py-1 font-mono text-[10px] uppercase tracking-[0.12em] text-ink-tertiary">
                  {tenant.status}
                </span>
              </button>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}

function CreateTenantForm({
  existing,
  onCreated,
}: {
  existing: TenantLifecycleRecord[];
  onCreated: (record: TenantLifecycleRecord) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const tenantId = String(form.get("tenant_id") || "").trim();
    if (!tenantId) {
      setError("Enter a tenant id.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const record = await createTenantLifecycle(tenantId);
      onCreated(record);
    } catch (caught: unknown) {
      if (caught instanceof ApiError && caught.status === 409) {
        const found = existing.find((tenant) => tenant.tenant_id === tenantId);
        if (found) {
          setError(`Tenant "${tenantId}" already exists — selected it for handoff.`);
          onCreated(found);
        } else {
          setError(`A tenant with id "${tenantId}" already exists.`);
        }
      } else {
        setError(formatApiError(caught));
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <p className="text-[13px] leading-relaxed text-ink-secondary">
        Creates the tenant <strong>inert</strong> (fail-closed): it exists but cannot
        act until an action policy is applied. Platform-gated and audited.
      </p>
      {error && (
        <div className="rounded border border-gold-primary/30 bg-gold-bg px-3 py-2 text-[13px] text-ink-primary">
          {error}
        </div>
      )}
      <label className="block">
        <span className="mb-1 block font-mono text-[11px] uppercase tracking-[0.12em] text-ink-tertiary">
          Tenant id
        </span>
        <input
          name="tenant_id"
          placeholder="tenant-2"
          className="h-11 w-full max-w-md rounded border border-border-subtle bg-surface-raised px-3 text-[14px] text-ink-primary focus:outline-none focus:border-gold-primary sm:h-10"
        />
      </label>
      <button
        type="submit"
        disabled={busy}
        className="inline-flex h-10 items-center gap-2 rounded bg-gold-primary px-4 text-[13px] font-semibold text-white hover:bg-gold-muted disabled:opacity-60"
      >
        {busy ? "Creating…" : "Create tenant (inert)"}
      </button>
    </form>
  );
}

function Handoff({ record }: { record: TenantLifecycleRecord }) {
  const framing = describeTenantStatus(record.status);
  return (
    <div className="space-y-3">
      <div className="rounded border border-border-subtle bg-surface-raised p-3 text-[13px] text-ink-secondary">
        <div className="flex items-center gap-2">
          <Check className="h-4 w-4 text-green-success" strokeWidth={1.8} />
          <span className="font-semibold text-ink-primary">{record.tenant_id}</span>
          <span className="rounded border border-border-subtle px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.12em] text-ink-tertiary">
            {framing.label}
          </span>
        </div>
        <p className="mt-2">{framing.detail}</p>
        <p className="mt-1 font-mono text-[11px] text-ink-tertiary">created {record.created_at}</p>
      </div>

      <div className="rounded border border-gold-primary/40 bg-gold-bg p-3 text-[13px] leading-relaxed text-ink-primary">
        <p className="flex items-center gap-2 font-semibold">
          <Lock className="h-4 w-4 text-gold-primary" strokeWidth={1.8} />
          This tenant cannot be configured from the Platform Console
        </p>
        <p className="mt-2">
          That is the tenant-isolation boundary — there is no cross-tenant
          configuration path. To configure{" "}
          <strong>{record.tenant_id}</strong>:
        </p>
        <ol className="mt-2 list-decimal space-y-1 pl-5">
          <li>
            In Auth0, create/grant a user with{" "}
            <code>tenant_id={record.tenant_id}</code> and the config roles
            (connector / policy / channel write + read), and a{" "}
            <strong>separate</strong> approver user with{" "}
            <code>tenant.config.approve</code> (dual control).
          </li>
          <li>Log into the Command Center as that user.</li>
          <li>
            Complete configuration there: channels → connectors → credentials →
            action policy.
          </li>
        </ol>
      </div>

      <a
        href={COMMAND_CENTER_URL}
        target="_blank"
        rel="noreferrer"
        className="inline-flex h-9 items-center gap-2 rounded border border-border-subtle px-3 text-[12px] text-ink-secondary hover:border-border-defined hover:text-ink-primary"
      >
        Open Command Center <ExternalLink className="h-3.5 w-3.5" strokeWidth={1.8} />
      </a>
    </div>
  );
}

function Step({
  index,
  title,
  children,
}: {
  index: number;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <article className="mb-4 rounded-lg border border-border-subtle bg-surface p-4">
      <div className="mb-3 flex items-center gap-3">
        <span className="flex h-7 w-7 items-center justify-center rounded-full border border-border-subtle font-mono text-[12px] text-ink-tertiary">
          {index}
        </span>
        <h2 className="text-[16px] font-semibold text-ink-primary">{title}</h2>
        <ArrowRight className="h-4 w-4 text-ink-quaternary" strokeWidth={1.6} />
      </div>
      <div className="pl-10">{children}</div>
    </article>
  );
}
