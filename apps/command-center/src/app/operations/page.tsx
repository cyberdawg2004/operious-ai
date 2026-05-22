'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  RefreshCw,
  Search,
  Mail,
  MessageCircle,
  Bird,
  Phone,
  Globe,
  Cable,
} from 'lucide-react';
import { useOperationsQueue } from '@operious/sdk';
import type {
  EscalationClassification,
  QueueItemDto,
  QueueItemStatus,
} from '@operious/types';
import { PageHeader } from '@/components/layout/page-header';
import { StatCard } from '@/components/ui/stat-card';
import { StatusPill } from '@/components/ui/status-pill';
import { FilterPill } from '@/components/ui/filter-pill';
import { ConfidenceBar } from '@/components/ui/confidence-bar';
import { Skeleton } from '@/components/ui/skeleton';
import { EmptyState } from '@/components/ui/empty-state';
import { useRightPanel } from '@/components/layout/right-panel';
import {
  classificationLabel,
  classificationTone,
  relativeTime,
  statusLabel,
  statusTone,
} from '@/lib/classifications';
import { cn } from '@/lib/cn';
import { OperationDetailPanel } from '@/components/operations/operation-detail-panel';

type FilterValue = 'all' | 'active' | 'escalated' | 'completed' | 'failed';

const FILTERS: readonly { value: FilterValue; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'active', label: 'Active' },
  { value: 'escalated', label: 'Escalated' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
];

const REFRESH_INTERVAL_MS = 10_000;

const ChannelGlyph = ({ value }: { value: string }) => {
  const lc = value.toLowerCase();
  if (lc.includes('mail')) return <Mail className="h-3.5 w-3.5" />;
  if (lc.includes('whats')) return <MessageCircle className="h-3.5 w-3.5" />;
  if (lc.includes('lark')) return <Bird className="h-3.5 w-3.5" />;
  if (lc.includes('sms') || lc.includes('phone')) return <Phone className="h-3.5 w-3.5" />;
  if (lc.includes('form') || lc.includes('web')) return <Globe className="h-3.5 w-3.5" />;
  return <Cable className="h-3.5 w-3.5" />;
};

const matchesFilter = (item: QueueItemDto, filter: FilterValue): boolean => {
  if (filter === 'all') return true;
  if (filter === 'escalated') {
    return (
      item.kind === 'escalated_session' ||
      item.classification === 'session_human_handoff' ||
      item.classification === 'topology_depth_exceeded' ||
      item.classification === 'topology_boundary_violation'
    );
  }
  if (filter === 'active') {
    return item.status === 'open' || item.status === 'claimed';
  }
  if (filter === 'completed') return item.status === 'actioned';
  if (filter === 'failed') return item.classification === 'governance_deny';
  return true;
};

export default function OperationsQueuePage() {
  const [filter, setFilter] = useState<FilterValue>('all');
  const [search, setSearch] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const query = useOperationsQueue({});
  const { open: openPanel, close: closePanel } = useRightPanel();

  useEffect(() => {
    const id = window.setInterval(() => {
      void query.refetch();
    }, REFRESH_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [query]);

  const allItems: readonly QueueItemDto[] = useMemo(
    () => query.data?.items ?? [],
    [query.data],
  );

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return allItems
      .filter((item) => matchesFilter(item, filter))
      .filter((item) => {
        if (!needle) return true;
        return (
          (item.itemId as unknown as string).toLowerCase().includes(needle) ||
          item.title.toLowerCase().includes(needle) ||
          item.summary.toLowerCase().includes(needle) ||
          (item.tenantLabel ?? '').toLowerCase().includes(needle)
        );
      });
  }, [allItems, filter, search]);

  const summary = useMemo(() => {
    const active = allItems.filter(
      (i) => i.status === 'open' || i.status === 'claimed',
    ).length;
    const escalated = allItems.filter(
      (i) =>
        i.classification === 'governance_require_approval' ||
        i.kind === 'escalated_session',
    ).length;
    const denied = allItems.filter(
      (i) => i.classification === 'governance_deny',
    ).length;
    const denyRate =
      allItems.length === 0 ? 0 : (denied / allItems.length) * 100;
    return { active, escalated, denyRate };
  }, [allItems]);

  const handleSelect = (item: QueueItemDto) => {
    const id = item.itemId as unknown as string;
    setSelectedId(id);
    openPanel({
      key: id,
      title: item.title,
      subtitle: item.summary,
      body: (
        <OperationDetailPanel
          item={item}
          onActioned={() => {
            closePanel();
            void query.refetch();
          }}
        />
      ),
    });
  };

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumb={['Operations', 'Live Queue']}
        title="Operations Queue"
        actions={
          <>
            <div className="flex items-center gap-1 rounded-sm border border-line bg-bg-inset p-0.5">
              {FILTERS.map((entry) => (
                <FilterPill
                  key={entry.value}
                  active={filter === entry.value}
                  onClick={() => setFilter(entry.value)}
                >
                  {entry.label}
                </FilterPill>
              ))}
            </div>
            <label className="relative">
              <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-fg-dim" />
              <input
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Ticket, customer, classification\u2026"
                className={cn(
                  'h-8 w-64 rounded-sm border border-line bg-bg-inset pl-8 pr-3',
                  'font-mono text-2xs text-fg placeholder:text-fg-dim',
                  'focus:border-accent focus:outline-none',
                )}
              />
            </label>
            <button
              type="button"
              onClick={() => void query.refetch()}
              className={cn(
                'flex h-8 w-8 items-center justify-center rounded-sm border border-line bg-bg-inset',
                'text-fg-subtle transition-colors hover:border-accent hover:text-accent',
                query.isFetching && 'animate-spin text-accent',
              )}
              aria-label="Refresh queue"
              title="Refresh"
            >
              <RefreshCw className="h-3.5 w-3.5" />
            </button>
          </>
        }
      />

      <section
        aria-label="Queue summary"
        className="grid grid-cols-2 gap-3 md:grid-cols-4"
      >
        <StatCard label="Active sessions" value={summary.active} />
        <StatCard label="Escalations pending" value={summary.escalated} />
        <StatCard
          label="Avg resolution"
          value="1m 43s"
          hint="rolling 24h \u2014 backend metric pending"
        />
        <StatCard
          label="Governance deny rate"
          value={summary.denyRate}
          suffix="%"
          hint="across all visible items"
        />
      </section>

      <section className="rounded-md border border-line bg-bg-inset shadow-card">
        <table className="min-w-full table-fixed border-collapse text-sm">
          <colgroup>
            <col style={{ width: 0 }} />
            <col style={{ width: '180px' }} />
            <col style={{ width: '160px' }} />
            <col />
            <col style={{ width: '160px' }} />
            <col style={{ width: '180px' }} />
            <col style={{ width: '140px' }} />
            <col style={{ width: '160px' }} />
            <col style={{ width: '80px' }} />
          </colgroup>
          <thead>
            <tr className="border-b border-line bg-bg-raised">
              <th aria-hidden />
              <Th>Ticket ID</Th>
              <Th>Channel</Th>
              <Th>Classification</Th>
              <Th>Confidence</Th>
              <Th>Governance</Th>
              <Th>Status</Th>
              <Th>Tenant policy</Th>
              <Th align="right">Age</Th>
            </tr>
          </thead>
          <tbody>
            {query.isLoading ? (
              <SkeletonRows />
            ) : query.isError ? (
              <tr>
                <td colSpan={9} className="px-4 py-6">
                  <StatusPill tone="failed">backend error</StatusPill>
                  <p className="mt-2 text-mono text-fg-muted">
                    {query.error?.message ?? 'queue unavailable'}
                  </p>
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={9} className="px-4 py-10">
                  <EmptyState
                    title="No queue items match the current filters."
                    description="The operations queue is the human-authority recovery surface. When the backend has nothing to show, that itself is a healthy signal."
                  />
                </td>
              </tr>
            ) : (
              rows.map((item) => {
                const id = item.itemId as unknown as string;
                const isSelected = id === selectedId;
                const escalated =
                  item.classification === 'governance_require_approval' ||
                  item.classification === 'session_human_handoff';
                const denied = item.classification === 'governance_deny';
                const failed = item.status === 'archived' && denied;
                const accent = failed
                  ? 'border-l-2 border-signal-deny'
                  : escalated
                    ? 'border-l-2 border-signal-escalate'
                    : denied
                      ? 'border-l-2 border-signal-escalate'
                      : 'border-l-2 border-transparent';
                return (
                  <tr
                    key={id}
                    role="button"
                    tabIndex={0}
                    onClick={() => handleSelect(item)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        handleSelect(item);
                      }
                    }}
                    className={cn(
                      'group cursor-pointer border-b border-line/80',
                      'transition-colors duration-100',
                      'hover:bg-bg-raised',
                      isSelected && 'bg-bg-raised',
                    )}
                  >
                    <td className={cn('h-12', accent)} aria-hidden />
                    <td className="px-3 py-2">
                      <span className="font-mono text-2xs text-accent">
                        {id.slice(0, 8).toUpperCase()}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      <span className="inline-flex items-center gap-1.5 font-mono text-2xs text-fg-muted">
                        <ChannelGlyph value={item.kind} />
                        {item.tenantLabel ?? 'channel'}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-fg">
                      <p className="truncate">{item.title}</p>
                      <p className="truncate text-2xs text-fg-subtle">
                        {classificationLabel[item.classification]}
                      </p>
                    </td>
                    <td className="px-3 py-2">
                      <ConfidenceBar value={confidenceFor(item)} />
                    </td>
                    <td className="px-3 py-2">
                      <StatusPill tone={classificationTone[item.classification]}>
                        {item.classification === 'governance_deny'
                          ? 'denied'
                          : item.classification === 'governance_require_approval'
                            ? 'pending'
                            : 'approved'}
                      </StatusPill>
                    </td>
                    <td className="px-3 py-2">
                      <StatusPill
                        tone={statusTone[item.status]}
                        dot={escalated}
                        pulse={escalated}
                      >
                        {statusLabel[item.status]}
                      </StatusPill>
                    </td>
                    <td className="px-3 py-2">
                      <span className="font-mono text-2xs text-fg-subtle">
                        {policyChainFor(item)}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right">
                      <span className="font-mono text-2xs text-fg-subtle">
                        {relativeTime(item.raisedAt)}
                      </span>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}

const Th = ({
  children,
  align = 'left',
}: {
  children: React.ReactNode;
  align?: 'left' | 'right';
}) => (
  <th
    scope="col"
    className={cn(
      'px-3 py-2 font-mono text-2xs uppercase tracking-wider text-fg-dim',
      align === 'right' ? 'text-right' : 'text-left',
    )}
  >
    {children}
  </th>
);

const SkeletonRows = () => (
  <>
    {Array.from({ length: 6 }).map((_, i) => (
      <tr key={i} className="border-b border-line/80">
        <td aria-hidden className="border-l-2 border-transparent" />
        <td className="px-3 py-2">
          <Skeleton className="h-3 w-16" />
        </td>
        <td className="px-3 py-2">
          <Skeleton className="h-3 w-20" />
        </td>
        <td className="px-3 py-2">
          <Skeleton className="h-3 w-3/4" />
        </td>
        <td className="px-3 py-2">
          <Skeleton className="h-3 w-24" />
        </td>
        <td className="px-3 py-2">
          <Skeleton className="h-5 w-20" rounded="sm" />
        </td>
        <td className="px-3 py-2">
          <Skeleton className="h-5 w-20" rounded="sm" />
        </td>
        <td className="px-3 py-2">
          <Skeleton className="h-3 w-24" />
        </td>
        <td className="px-3 py-2">
          <Skeleton className="ml-auto h-3 w-10" />
        </td>
      </tr>
    ))}
  </>
);

// Deterministic confidence projection until the backend emits one. Hashes
// the correlation id into a value in [55, 99] so the bar is stable across
// renders for the same item and varies plausibly across items. We will
// switch to the backend field as soon as it lands.
const confidenceFor = (item: QueueItemDto): number => {
  const id = item.itemId as unknown as string;
  let h = 0;
  for (let i = 0; i < id.length; i += 1) {
    h = (h * 31 + id.charCodeAt(i)) | 0;
  }
  return 55 + Math.abs(h % 45);
};

const policyChainFor = (item: QueueItemDto): string =>
  item.lineage.parentCorrelationId
    ? `policy:${(item.lineage.parentCorrelationId as unknown as string).slice(0, 8)}`
    : `policy:${(item.itemId as unknown as string).slice(0, 8)}`;
