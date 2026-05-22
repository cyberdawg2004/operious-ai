'use client';

import { useMemo, useState } from 'react';
import { Plus, ShieldCheck } from 'lucide-react';
import {
  useCreatePolicy,
  useTenantPolicies,
  useUpdatePolicy,
} from '@operious/sdk';
import type {
  TenantGovernancePolicyDto,
  TenantGovernancePolicyStatus,
} from '@operious/types';
import { toast } from 'sonner';
import { PageHeader } from '@/components/layout/page-header';
import { StatusPill } from '@/components/ui/status-pill';
import { Skeleton } from '@/components/ui/skeleton';
import { EmptyState } from '@/components/ui/empty-state';
import { useRightPanel } from '@/components/layout/right-panel';
import { cn } from '@/lib/cn';

const STATUS_TONE: Record<
  TenantGovernancePolicyStatus,
  'active' | 'pending' | 'denied' | 'neutral'
> = {
  active: 'active',
  pending_approval: 'pending',
  draft: 'neutral',
  retired: 'neutral',
};

const TYPE_GROUPS: readonly string[] = [
  'refund_limit',
  'rma_threshold',
  'escalation_trigger',
  'auto_approval_limit',
  'authorization_rule',
];

const TYPE_LABEL: Record<string, string> = {
  refund_limit: 'Refund Limits',
  rma_threshold: 'RMA Thresholds',
  escalation_trigger: 'Escalation Triggers',
  auto_approval_limit: 'Auto-Approval Limits',
  authorization_rule: 'Authorization Rules',
};

export default function GovernancePoliciesPage() {
  const query = useTenantPolicies();
  const { open } = useRightPanel();

  const grouped = useMemo(() => {
    const items = query.data?.items ?? [];
    const buckets = new Map<string, TenantGovernancePolicyDto[]>();
    for (const policy of items) {
      const key = policy.policyType;
      const arr = buckets.get(key) ?? [];
      arr.push(policy);
      buckets.set(key, arr);
    }
    return buckets;
  }, [query.data]);

  const openEditor = (policy: TenantGovernancePolicyDto | null) => {
    open({
      key: policy?.policyId ?? 'new',
      title: policy
        ? TYPE_LABEL[policy.policyType] ?? policy.policyType
        : 'Create Policy',
      subtitle: policy
        ? `v${policy.version} \u00b7 approved by ${policy.approvedBy}`
        : 'New tenant policy',
      body: (
        <PolicyEditor
          policy={policy}
          onSaved={() => void query.refetch()}
        />
      ),
    });
  };

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumb={['Governance', 'Policies']}
        title="Governance Policies"
        actions={
          <button
            type="button"
            onClick={() => openEditor(null)}
            className={cn(
              'flex h-8 items-center gap-1.5 rounded-sm border border-accent bg-accent/15 px-3',
              'font-mono text-2xs uppercase tracking-wider text-accent',
              'transition-colors hover:bg-accent/25',
            )}
          >
            <Plus className="h-3.5 w-3.5" />
            Create Policy
          </button>
        }
      />

      {query.isLoading ? (
        <div className="space-y-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-32" rounded="md" />
          ))}
        </div>
      ) : query.isError ? (
        <div className="rounded-md border border-signal-deny/30 bg-signal-deny/5 p-6">
          <StatusPill tone="failed">backend error</StatusPill>
          <p className="mt-2 font-mono text-2xs text-signal-deny">
            {query.error?.message}
          </p>
        </div>
      ) : grouped.size === 0 ? (
        <EmptyState
          icon={ShieldCheck}
          title="No governance policies configured for this tenant."
          description="Create refund limits, RMA thresholds, escalation triggers, auto-approval limits, and authorization rules. Activation requires admin signature."
        />
      ) : (
        <div className="space-y-6">
          {TYPE_GROUPS.map((type) => {
            const items = grouped.get(type) ?? [];
            if (items.length === 0) return null;
            return (
              <section key={type}>
                <h2 className="mb-2 font-display text-lg text-fg">
                  {TYPE_LABEL[type] ?? type.replace(/_/g, ' ')}
                </h2>
                <div className="grid gap-3 md:grid-cols-2">
                  {items.map((policy) => (
                    <PolicyCard
                      key={policy.policyId as unknown as string}
                      policy={policy}
                      onOpen={() => openEditor(policy)}
                    />
                  ))}
                </div>
              </section>
            );
          })}
          {Array.from(grouped.entries())
            .filter(([key]) => !TYPE_GROUPS.includes(key))
            .map(([type, items]) => (
              <section key={type}>
                <h2 className="mb-2 font-display text-lg text-fg">
                  {TYPE_LABEL[type] ?? type.replace(/_/g, ' ')}
                </h2>
                <div className="grid gap-3 md:grid-cols-2">
                  {items.map((policy) => (
                    <PolicyCard
                      key={policy.policyId as unknown as string}
                      policy={policy}
                      onOpen={() => openEditor(policy)}
                    />
                  ))}
                </div>
              </section>
            ))}
        </div>
      )}
    </div>
  );
}

const PolicyCard = ({
  policy,
  onOpen,
}: {
  policy: TenantGovernancePolicyDto;
  onOpen: () => void;
}) => (
  <button
    type="button"
    onClick={onOpen}
    className={cn(
      'group flex flex-col gap-2 rounded-md border border-line bg-bg-inset p-4 text-left shadow-card',
      'transition-shadow duration-150 hover:shadow-raised',
    )}
  >
    <div className="flex items-center justify-between gap-2">
      <span className="font-mono text-2xs uppercase tracking-wider text-fg-subtle">
        {policy.policyType.replace(/_/g, ' ')}
      </span>
      <StatusPill tone={STATUS_TONE[policy.status]}>
        {policy.status.replace(/_/g, ' ')}
      </StatusPill>
    </div>
    <p className="font-display text-base text-fg">
      v{policy.version}
    </p>
    <pre className="rounded-sm border border-line bg-bg p-2 font-mono text-2xs text-fg-muted">
      {JSON.stringify(policy.parameters, null, 2)}
    </pre>
    <div className="mt-1 flex items-center justify-between text-mono text-fg-dim">
      <span>effective {policy.effectiveFrom}</span>
      <span>approved by {policy.approvedBy}</span>
    </div>
  </button>
);

const PolicyEditor = ({
  policy,
  onSaved,
}: {
  policy: TenantGovernancePolicyDto | null;
  onSaved: () => void;
}) => {
  const [policyType, setPolicyType] = useState<string>(
    policy?.policyType ?? TYPE_GROUPS[0] ?? 'refund_limit',
  );
  const [parameters, setParameters] = useState(
    JSON.stringify(policy?.parameters ?? {}, null, 2),
  );
  const [effectiveFrom, setEffectiveFrom] = useState(
    policy?.effectiveFrom ?? new Date().toISOString(),
  );
  const [parseError, setParseError] = useState<string | null>(null);

  const create = useCreatePolicy();
  const update = useUpdatePolicy();

  const submit = async () => {
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(parameters);
    } catch (cause) {
      setParseError(cause instanceof Error ? cause.message : 'JSON invalid');
      return;
    }
    setParseError(null);
    try {
      if (policy) {
        await update.mutateAsync({
          policyId: policy.policyId,
          parameters: parsed,
          effectiveFrom,
        });
        toast.success('Policy update submitted', {
          description:
            'Awaiting admin signature. Backend confirms activation.',
        });
      } else {
        await create.mutateAsync({
          policyType,
          parameters: parsed,
          effectiveFrom,
        });
        toast.success('Policy draft created', {
          description: 'Submit for approval to activate.',
        });
      }
      onSaved();
    } catch (cause) {
      toast.error('Backend declined', {
        description:
          cause instanceof Error ? cause.message : 'transport error',
      });
    }
  };

  const isPending = create.isPending || update.isPending;

  return (
    <div className="space-y-4">
      <label className="block">
        <span className="text-mono text-fg-dim">policy type</span>
        <select
          value={policyType}
          onChange={(event) => setPolicyType(event.target.value)}
          disabled={Boolean(policy)}
          className={cn(
            'mt-1 w-full rounded-sm border border-line bg-bg px-3 py-2',
            'font-mono text-2xs text-fg outline-none focus:border-accent',
          )}
        >
          {TYPE_GROUPS.map((key) => (
            <option key={key} value={key}>
              {TYPE_LABEL[key] ?? key}
            </option>
          ))}
        </select>
      </label>

      <label className="block">
        <span className="text-mono text-fg-dim">parameters (JSON)</span>
        <textarea
          value={parameters}
          onChange={(event) => setParameters(event.target.value)}
          rows={10}
          className={cn(
            'mt-1 w-full rounded-sm border border-line bg-bg px-3 py-2',
            'font-mono text-2xs text-fg outline-none focus:border-accent',
            parseError && 'border-signal-deny',
          )}
        />
        {parseError ? (
          <p className="mt-1 text-mono text-signal-deny">{parseError}</p>
        ) : null}
      </label>

      <label className="block">
        <span className="text-mono text-fg-dim">effective from</span>
        <input
          type="datetime-local"
          value={effectiveFrom.slice(0, 16)}
          onChange={(event) =>
            setEffectiveFrom(new Date(event.target.value).toISOString())
          }
          className={cn(
            'mt-1 w-full rounded-sm border border-line bg-bg px-3 py-2',
            'font-mono text-2xs text-fg outline-none focus:border-accent',
          )}
        />
      </label>

      <p className="text-2xs text-fg-subtle">
        Approval workflow: every policy mutation requires an admin signature.
        The frontend records the intent; the backend governance evaluator
        confirms activation.
      </p>

      <div className="flex items-center justify-end gap-2 border-t border-line pt-3">
        <button
          type="button"
          onClick={submit}
          disabled={isPending}
          className={cn(
            'rounded-sm border border-accent bg-accent/15 px-3 py-1.5',
            'font-mono text-2xs uppercase tracking-wider text-accent',
            'transition-colors hover:bg-accent/25',
            isPending && 'opacity-50',
          )}
        >
          {isPending ? 'Submitting\u2026' : policy ? 'Save changes' : 'Submit for approval'}
        </button>
      </div>
    </div>
  );
};
