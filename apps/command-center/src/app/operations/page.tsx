'use client';

import { useMemo, useState } from 'react';
import { useOperationsQueue } from '@operious/sdk';
import { stableSortBy } from '@operious/shared';
import {
  Badge,
  Card,
  DataTable,
  Drawer,
  EnvelopeRenderer,
  JsonInspector,
  type BadgeTone,
  type DataTableColumn,
} from '@operious/ui';
import { LineageRibbon } from '@operious/observability';
import type {
  EscalationClassification,
  QueueItemDto,
  QueueItemKind,
  QueueItemStatus,
} from '@operious/types';
import { useLocale } from '@/locale/provider';

const classificationTone: Record<EscalationClassification, BadgeTone> = {
  governance_deny: 'deny',
  governance_require_approval: 'pending',
  arbitration_deadlock: 'deadlock',
  arbitration_inconclusive: 'deadlock',
  topology_boundary_violation: 'deny',
  topology_depth_exceeded: 'escalate',
  session_human_handoff: 'escalate',
};

const statusTone: Record<QueueItemStatus, BadgeTone> = {
  open: 'pending',
  claimed: 'info',
  actioned: 'allow',
  deferred: 'escalate',
  archived: 'neutral',
};

const KIND_FILTERS: readonly { readonly value: QueueItemKind | 'all'; readonly label: string }[] = [
  { value: 'all', label: 'all kinds' },
  { value: 'escalated_session', label: 'sessions' },
  { value: 'denied_governance_decision', label: 'governance' },
  { value: 'arbitration_deadlock', label: 'arbitration' },
  { value: 'topology_escalation', label: 'topology' },
];

const STATUS_FILTERS: readonly { readonly value: QueueItemStatus | 'all'; readonly label: string }[] = [
  { value: 'all', label: 'any status' },
  { value: 'open', label: 'open' },
  { value: 'claimed', label: 'claimed' },
  { value: 'deferred', label: 'deferred' },
  { value: 'archived', label: 'archived' },
];

export default function OperationsQueuePage() {
  const { t } = useLocale();
  const [kindFilter, setKindFilter] = useState<QueueItemKind | 'all'>('all');
  const [statusFilter, setStatusFilter] = useState<QueueItemStatus | 'all'>('all');
  const [selected, setSelected] = useState<QueueItemDto | null>(null);

  const query = useOperationsQueue({
    kind: kindFilter === 'all' ? undefined : kindFilter,
    status: statusFilter === 'all' ? undefined : statusFilter,
  });

  const rows = useMemo(() => {
    if (!query.data) return [];
    return stableSortBy([...query.data.items], (item) => `${item.raisedAt}|${item.itemId}`);
  }, [query.data]);

  const columns: DataTableColumn<QueueItemDto>[] = [
    {
      key: 'classification',
      header: t.operations.columns.classification,
      width: '220px',
      render: (row) => (
        <Badge tone={classificationTone[row.classification]}>
          {row.classification.replace(/_/g, ' ')}
        </Badge>
      ),
    },
    {
      key: 'title',
      header: t.operations.columns.title,
      render: (row) => (
        <div className="space-y-1">
          <p className="text-fg">{row.title}</p>
          <p className="text-2xs text-fg-subtle font-mono">{row.summary}</p>
        </div>
      ),
    },
    {
      key: 'status',
      header: t.operations.columns.status,
      width: '120px',
      render: (row) => <Badge tone={statusTone[row.status]}>{row.status}</Badge>,
    },
    {
      key: 'tenant',
      header: t.operations.columns.tenant,
      width: '180px',
      render: (row) => (
        <span className="font-mono text-2xs text-fg-muted">
          {row.tenantLabel ?? '—'}
        </span>
      ),
    },
    {
      key: 'raisedAt',
      header: t.operations.columns.raisedAt,
      width: '200px',
      render: (row) => (
        <span className="font-mono text-2xs text-fg-muted">{row.raisedAt}</span>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <p className="text-mono text-fg-subtle">/ operations queue</p>
        <h1 className="font-display text-3xl text-fg">{t.operations.title}</h1>
        <p className="max-w-3xl text-sm text-fg-muted">{t.operations.description}</p>
      </header>

      <Card tone="default" className="space-y-4">
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <span className="text-mono text-fg-subtle">kind:</span>
            {KIND_FILTERS.map((entry) => (
              <FilterChip
                key={entry.value}
                active={kindFilter === entry.value}
                onClick={() => setKindFilter(entry.value as QueueItemKind | 'all')}
              >
                {entry.label}
              </FilterChip>
            ))}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-mono text-fg-subtle">status:</span>
            {STATUS_FILTERS.map((entry) => (
              <FilterChip
                key={entry.value}
                active={statusFilter === entry.value}
                onClick={() => setStatusFilter(entry.value as QueueItemStatus | 'all')}
              >
                {entry.label}
              </FilterChip>
            ))}
          </div>
        </div>

        <EnvelopeRenderer
          status={
            query.isLoading ? 'pending' : query.isError ? 'error' : 'ok'
          }
          value={query.data}
          error={query.error ? { code: 'sdk_error', message: query.error.message } : undefined}
        >
          {(_) => (
            <DataTable
              rows={rows}
              columns={columns}
              rowKey={(row) => row.itemId as unknown as string}
              onRowClick={(row) => setSelected(row)}
              emptyLabel={t.operations.empty}
            />
          )}
        </EnvelopeRenderer>
      </Card>

      <Drawer
        open={Boolean(selected)}
        onClose={() => setSelected(null)}
        title={selected?.title ?? ''}
        subtitle={selected?.summary}
      >
        {selected ? (
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <Badge tone={classificationTone[selected.classification]}>
                {selected.classification.replace(/_/g, ' ')}
              </Badge>
              <Badge tone={statusTone[selected.status]}>{selected.status}</Badge>
              <Badge tone="info">{selected.kind.replace(/_/g, ' ')}</Badge>
            </div>
            <LineageRibbon lineage={selected.lineage} />
            <Card tone="inset" className="space-y-2">
              <p className="text-mono text-fg-subtle">payload</p>
              <JsonInspector value={selected} />
            </Card>
            <p className="text-mono text-fg-subtle">
              {t.common.authorityNotice}
            </p>
          </div>
        ) : null}
      </Drawer>
    </div>
  );
}

const FilterChip = ({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) => (
  <button
    type="button"
    onClick={onClick}
    className={`rounded-sm border px-2 py-1 font-mono text-2xs uppercase tracking-wider transition-colors ${
      active
        ? 'border-line-strong bg-bg-raised text-fg'
        : 'border-line bg-bg-inset text-fg-subtle hover:text-fg'
    }`}
  >
    {children}
  </button>
);
