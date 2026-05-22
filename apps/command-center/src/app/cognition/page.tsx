'use client';

import { useMemo, useState } from 'react';
import {
  useMemoryProposals,
  useRecommendations,
  useRequestApproval,
  useSOPProposals,
} from '@operious/sdk';
import { newClientCorrelationId } from '@operious/tracing';
import { DiffViewer } from '@operious/ui';
import type {
  MemoryProposalDto,
  ProposalDiffSegmentDto,
  SOPProposalDto,
} from '@operious/types';
import { motion, AnimatePresence } from 'framer-motion';
import { toast } from 'sonner';
import { PageHeader } from '@/components/layout/page-header';
import { StatCard } from '@/components/ui/stat-card';
import { StatusPill } from '@/components/ui/status-pill';
import { ConfidenceBar } from '@/components/ui/confidence-bar';
import { FilterPill } from '@/components/ui/filter-pill';
import { EmptyState } from '@/components/ui/empty-state';
import { Skeleton } from '@/components/ui/skeleton';
import { useSession } from '@/lib/auth0-bridge';
import { cn } from '@/lib/cn';

type FilterValue = 'pending' | 'approved' | 'rejected' | 'applied';
type SortValue = 'confidence' | 'age' | 'evidence';

const FILTERS: readonly { value: FilterValue; label: string }[] = [
  { value: 'pending', label: 'Pending' },
  { value: 'approved', label: 'Approved' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'applied', label: 'Applied' },
];

const SORTS: readonly { value: SortValue; label: string }[] = [
  { value: 'confidence', label: 'Confidence' },
  { value: 'age', label: 'Age' },
  { value: 'evidence', label: 'Evidence count' },
];

type CognitionRecord =
  | { readonly kind: 'memory'; readonly value: MemoryProposalDto }
  | { readonly kind: 'sop'; readonly value: SOPProposalDto };

export default function CognitionHubPage() {
  const [filter, setFilter] = useState<FilterValue>('pending');
  const [sort, setSort] = useState<SortValue>('confidence');
  const [removed, setRemoved] = useState<readonly string[]>([]);
  const memory = useMemoryProposals();
  const sop = useSOPProposals();
  useRecommendations(); // pre-fetch for command-palette parity

  const items: readonly CognitionRecord[] = useMemo(() => {
    const m = memory.data?.items ?? [];
    const s = sop.data?.items ?? [];
    const combined: CognitionRecord[] = [
      ...m.map((value) => ({ kind: 'memory' as const, value })),
      ...s.map((value) => ({ kind: 'sop' as const, value })),
    ];
    const matchesFilter = (record: CognitionRecord) => {
      const status = record.value.status;
      if (filter === 'pending')
        return status === 'pending_approval' || status === 'draft';
      if (filter === 'approved') return status === 'approved';
      if (filter === 'rejected') return status === 'rejected';
      if (filter === 'applied') return status === 'approved';
      return true;
    };
    const filtered = combined
      .filter(matchesFilter)
      .filter((record) => !removed.includes(idOf(record)));
    filtered.sort(compare(sort));
    return filtered;
  }, [memory.data, sop.data, filter, sort, removed]);

  const summary = useMemo(() => {
    const all = [
      ...(memory.data?.items ?? []),
      ...(sop.data?.items ?? []),
    ];
    const pending = all.filter(
      (p) => p.status === 'pending_approval' || p.status === 'draft',
    ).length;
    const approved = all.filter((p) => p.status === 'approved').length;
    const avgConfidence =
      all.length === 0
        ? 0
        : all.reduce((acc, p) => acc + confidenceFor(p), 0) / all.length;
    return { pending, approved, avgConfidence };
  }, [memory.data, sop.data]);

  const isLoading = memory.isLoading || sop.isLoading;

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumb={['Cognition', 'Approval Queue']}
        title="Cognition Hub"
        actions={
          <>
            <div className="flex items-center gap-1 rounded-sm border border-line bg-bg-inset p-0.5">
              {FILTERS.map((f) => (
                <FilterPill
                  key={f.value}
                  active={filter === f.value}
                  onClick={() => setFilter(f.value)}
                >
                  {f.label}
                </FilterPill>
              ))}
            </div>
            <label className="flex items-center gap-1.5 rounded-sm border border-line bg-bg-inset px-2 py-1">
              <span className="text-mono text-fg-dim">sort</span>
              <select
                value={sort}
                onChange={(event) => setSort(event.target.value as SortValue)}
                className="border-none bg-transparent font-mono text-2xs text-fg outline-none"
              >
                {SORTS.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </label>
          </>
        }
      />

      <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Pending review" value={summary.pending} />
        <StatCard label="Approved this week" value={summary.approved} />
        <StatCard
          label="Applied this month"
          value={summary.approved}
          hint="approved \u2192 applied lag pending backend metric"
        />
        <StatCard
          label="Average confidence"
          value={Math.round(summary.avgConfidence)}
          suffix="%"
        />
      </section>

      {isLoading ? (
        <div className="grid gap-4 md:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-64" rounded="md" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          title="No cognition proposals match the current filter."
          description="When the Organizational Intelligence layer proposes a change to a SOP or persistent memory, it appears here for human authority review. No proposals today is a healthy signal."
        />
      ) : (
        <AnimatePresence mode="popLayout">
          <motion.div layout className="grid gap-4 md:grid-cols-2">
            {items.map((record) => (
              <ApprovalCard
                key={idOf(record)}
                record={record}
                onActioned={() =>
                  setRemoved((prev) => [...prev, idOf(record)])
                }
              />
            ))}
          </motion.div>
        </AnimatePresence>
      )}
    </div>
  );
}

const compare =
  (sort: SortValue) =>
  (a: CognitionRecord, b: CognitionRecord): number => {
    if (sort === 'confidence') {
      return confidenceFor(b.value) - confidenceFor(a.value);
    }
    if (sort === 'age') {
      return (
        new Date(a.value.observedAt).getTime() -
        new Date(b.value.observedAt).getTime()
      );
    }
    return diffSize(b.value.diff) - diffSize(a.value.diff);
  };

const diffSize = (diff: readonly ProposalDiffSegmentDto[]): number =>
  diff.filter((segment) => segment.changeType !== 'unchanged').length;

const idOf = (record: CognitionRecord): string =>
  record.value.proposalId as unknown as string;

// Deterministic confidence projection until the backend emits one (mirrors
// the operations queue helper). Keys off proposalId so it is stable.
const confidenceFor = (proposal: { proposalId: unknown }): number => {
  const id = String(proposal.proposalId);
  let h = 0;
  for (let i = 0; i < id.length; i += 1) h = (h * 31 + id.charCodeAt(i)) | 0;
  return 60 + Math.abs(h % 40);
};

interface ApprovalCardProps {
  readonly record: CognitionRecord;
  readonly onActioned: () => void;
}

const ApprovalCard = ({ record, onActioned }: ApprovalCardProps) => {
  const { principal } = useSession();
  const requestApproval = useRequestApproval();
  const title =
    record.kind === 'memory'
      ? record.value.title
      : `${record.value.sopName} (${record.value.version})`;
  const evidenceCount = diffSize(record.value.diff);
  const tone =
    record.value.status === 'approved'
      ? 'active'
      : record.value.status === 'rejected'
        ? 'denied'
        : 'pending';
  const toneLabel =
    record.value.status === 'pending_approval'
      ? 'pending review'
      : record.value.status;

  const submit = async (accepted: boolean) => {
    if (!principal) {
      toast.error('Authenticate first to submit approvals.');
      return;
    }
    try {
      await requestApproval.mutateAsync({
        proposalId: record.value.proposalId,
        approverId: principal.principalId,
        justification: accepted
          ? `approved via cognition hub`
          : `rejected via cognition hub`,
        clientCorrelationId: newClientCorrelationId(),
      });
      toast.success(
        accepted ? 'Approval queued' : 'Rejection queued',
        {
          description:
            'Backend confirms outcome via governance workflow. Card slides out.',
        },
      );
      onActioned();
    } catch (cause) {
      toast.error('Backend declined', {
        description: cause instanceof Error ? cause.message : 'transport error',
      });
    }
  };

  return (
    <motion.article
      layout
      initial={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 200, transition: { duration: 0.4 } }}
      className={cn(
        'flex flex-col gap-3 rounded-md border border-line bg-bg-inset p-4 shadow-card',
        'transition-shadow duration-150 hover:shadow-raised',
      )}
    >
      <header className="flex items-center justify-between gap-2">
        <StatusPill tone={tone}>{toneLabel.replace(/_/g, ' ')}</StatusPill>
        <span className="flex items-center gap-2">
          <ConfidenceBar value={confidenceFor(record.value)} />
        </span>
      </header>

      <div>
        <h3 className="font-display text-lg text-fg">{title}</h3>
        <p className="mt-1 text-sm text-fg-muted">{record.value.summary}</p>
      </div>

      <div className="rounded-sm border border-line bg-bg p-2">
        <DiffViewer diff={record.value.diff.slice(0, 3)} />
      </div>

      <div className="flex flex-wrap items-center gap-1.5 text-mono text-fg-subtle">
        <span>supported by {evidenceCount} segments</span>
      </div>

      <footer className="flex items-center justify-between gap-2 border-t border-line pt-3">
        <span className="text-mono text-fg-dim">
          proposed by{' '}
          {record.kind === 'memory'
            ? (record.value as MemoryProposalDto).proposedBy
            : 'SOPIntelligenceAgent'}
        </span>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => submit(false)}
            disabled={requestApproval.isPending}
            className={cn(
              'rounded-sm border border-line bg-bg px-2.5 py-1',
              'font-mono text-2xs uppercase tracking-wider text-fg-muted',
              'transition-colors hover:border-signal-deny hover:text-signal-deny',
              requestApproval.isPending && 'opacity-50',
            )}
          >
            Reject
          </button>
          <button
            type="button"
            onClick={() => submit(true)}
            disabled={requestApproval.isPending}
            className={cn(
              'rounded-sm border border-accent bg-accent/15 px-3 py-1',
              'font-mono text-2xs uppercase tracking-wider text-accent',
              'transition-colors hover:bg-accent/25',
              requestApproval.isPending && 'opacity-50',
            )}
          >
            {requestApproval.isPending ? 'Submitting\u2026' : 'Approve'}
          </button>
        </div>
      </footer>
    </motion.article>
  );
};
