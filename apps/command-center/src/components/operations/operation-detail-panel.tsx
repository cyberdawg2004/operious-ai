'use client';

import { useState } from 'react';
import { useRequestApproval } from '@operious/sdk';
import { newClientCorrelationId } from '@operious/tracing';
import type { QueueItemDto } from '@operious/types';
import { useSession } from '@/lib/auth0-bridge';
import { StatusPill } from '@/components/ui/status-pill';
import { FilterPill } from '@/components/ui/filter-pill';
import { cn } from '@/lib/cn';
import {
  classificationLabel,
  classificationTone,
  relativeTime,
  statusLabel,
  statusTone,
} from '@/lib/classifications';
import { toast } from 'sonner';

interface OperationDetailPanelProps {
  readonly item: QueueItemDto;
  readonly onActioned: () => void;
}

type Tab = 'overview' | 'timeline' | 'governance' | 'knowledge' | 'actions';

const TABS: readonly { value: Tab; label: string }[] = [
  { value: 'overview', label: 'Overview' },
  { value: 'timeline', label: 'Timeline' },
  { value: 'governance', label: 'Governance' },
  { value: 'knowledge', label: 'Knowledge' },
  { value: 'actions', label: 'Actions' },
];

export const OperationDetailPanel = ({
  item,
  onActioned,
}: OperationDetailPanelProps) => {
  const [tab, setTab] = useState<Tab>('overview');
  const [justification, setJustification] = useState('');
  const requestApproval = useRequestApproval();
  const { principal } = useSession();
  const requiresApproval =
    item.classification === 'governance_require_approval' ||
    item.classification === 'session_human_handoff';

  const submitApproval = async (accepted: boolean) => {
    if (!principal) {
      toast.error('No principal bound', {
        description: 'Sign in before requesting approval.',
      });
      return;
    }
    if (!justification.trim()) {
      toast.error('Justification required', {
        description: 'Manager approval must always carry a justification.',
      });
      return;
    }
    try {
      await requestApproval.mutateAsync({
        proposalId: item.itemId as unknown as never,
        approverId: principal.principalId,
        justification: `[${accepted ? 'APPROVE' : 'REJECT'}] ${justification.trim()}`,
        clientCorrelationId: newClientCorrelationId(),
      });
      toast.success(
        accepted ? 'Approval submitted' : 'Rejection submitted',
        {
          description:
            'Backend governance workflow will confirm the decision. The frontend does not auto-confirm.',
        },
      );
      onActioned();
    } catch (cause) {
      toast.error('Backend declined', {
        description:
          cause instanceof Error ? cause.message : 'unknown transport error',
      });
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <StatusPill tone={classificationTone[item.classification]}>
          {classificationLabel[item.classification]}
        </StatusPill>
        <StatusPill tone={statusTone[item.status]}>
          {statusLabel[item.status]}
        </StatusPill>
        <span className="font-mono text-2xs text-fg-subtle">
          raised {relativeTime(item.raisedAt)} ago
        </span>
      </div>

      <nav className="flex items-center gap-1 rounded-sm border border-line bg-bg p-0.5">
        {TABS.map((t) => (
          <FilterPill
            key={t.value}
            active={tab === t.value}
            onClick={() => setTab(t.value)}
          >
            {t.label}
          </FilterPill>
        ))}
      </nav>

      {tab === 'overview' ? (
        <Section title="Session metadata">
          <Field label="Item ID" value={item.itemId as unknown as string} />
          <Field label="Kind" value={item.kind.replace(/_/g, ' ')} />
          <Field
            label="Tenant"
            value={item.tenantLabel ?? '\u2014'}
          />
          {item.sessionId ? (
            <Field
              label="Session"
              value={item.sessionId as unknown as string}
            />
          ) : null}
          <Field label="Summary" value={item.summary} multiline />
        </Section>
      ) : null}

      {tab === 'timeline' ? (
        <Section title="Causality">
          <Field
            label="Correlation"
            value={item.lineage.correlationId as unknown as string}
          />
          <Field label="Sequence" value={String(item.lineage.sequence)} />
          {item.lineage.parentCorrelationId ? (
            <Field
              label="Parent"
              value={item.lineage.parentCorrelationId as unknown as string}
            />
          ) : null}
          <Field label="Observed" value={item.lineage.observedAt} />
          <p className="mt-2 text-2xs text-fg-subtle">
            Full event timeline is available in the Trace Inspector (G then T).
          </p>
        </Section>
      ) : null}

      {tab === 'governance' ? (
        <Section title="Governance trace">
          <Field
            label="Classification"
            value={classificationLabel[item.classification]}
          />
          <p className="text-2xs text-fg-subtle">
            The frontend visualises the governance verdict; the backend owns
            it. Use the Trace Inspector for the full evaluation chain.
          </p>
        </Section>
      ) : null}

      {tab === 'knowledge' ? (
        <Section title="Knowledge attachments">
          <p className="text-mono text-fg-subtle">
            knowledge attachment surface pending.
          </p>
        </Section>
      ) : null}

      {tab === 'actions' && !requiresApproval ? (
        <Section title="Actions">
          <p className="text-mono text-fg-subtle">
            No human authority action required.
          </p>
        </Section>
      ) : null}

      {tab === 'actions' && requiresApproval ? (
        <Section title="Manager approval">
          <label className="block">
            <span className="text-mono text-fg-dim">justification (required)</span>
            <textarea
              value={justification}
              onChange={(event) => setJustification(event.target.value)}
              rows={4}
              placeholder="Why is this approval the right operational decision?"
              className={cn(
                'mt-1 w-full rounded-sm border border-line bg-bg px-3 py-2',
                'font-sans text-sm text-fg placeholder:text-fg-dim',
                'focus:border-accent focus:outline-none',
              )}
            />
          </label>
          <p className="text-2xs text-fg-subtle">
            The frontend never auto-confirms. Submitting opens a backend
            governed approval workflow and the backend admits or declines.
          </p>
        </Section>
      ) : null}

      {tab === 'actions' && requiresApproval ? (
        <div className="-mx-5 -mb-4 mt-2 flex items-center justify-end gap-2 border-t border-line bg-bg-raised px-5 py-3">
          <button
            type="button"
            disabled={requestApproval.isPending}
            onClick={() => submitApproval(false)}
            className={cn(
              'rounded-sm border border-line bg-bg-inset px-3 py-1.5',
              'font-mono text-2xs uppercase tracking-wider text-fg-muted',
              'transition-colors hover:border-signal-deny hover:text-signal-deny',
              requestApproval.isPending && 'opacity-50',
            )}
          >
            Reject
          </button>
          <button
            type="button"
            disabled={requestApproval.isPending}
            onClick={() => submitApproval(true)}
            className={cn(
              'rounded-sm border border-accent bg-accent/15 px-3 py-1.5',
              'font-mono text-2xs uppercase tracking-wider text-accent',
              'transition-colors hover:bg-accent/25',
              requestApproval.isPending && 'opacity-50',
            )}
          >
            {requestApproval.isPending ? 'Submitting\u2026' : 'Approve'}
          </button>
        </div>
      ) : null}
    </div>
  );
};

const Section = ({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) => (
  <section className="rounded-md border border-line bg-bg p-4">
    <p className="mb-3 text-mono text-fg-dim">{title}</p>
    <div className="space-y-2.5">{children}</div>
  </section>
);

const Field = ({
  label,
  value,
  multiline = false,
}: {
  label: string;
  value: string;
  multiline?: boolean;
}) => (
  <div className="grid grid-cols-3 gap-2">
    <span className="text-mono text-fg-dim">{label}</span>
    <span
      className={cn(
        'col-span-2 font-mono text-2xs text-fg-muted',
        multiline ? 'whitespace-pre-wrap break-words' : 'truncate',
      )}
    >
      {value}
    </span>
  </div>
);
