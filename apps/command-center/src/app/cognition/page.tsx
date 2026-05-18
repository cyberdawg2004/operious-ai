'use client';

import { useState } from 'react';
import {
  useMemoryProposals,
  useRecommendations,
  useRequestApproval,
  useSOPProposals,
} from '@operious/sdk';
import { newClientCorrelationId } from '@operious/tracing';
import { useAuth } from '@operious/auth';
import {
  Badge,
  Button,
  Card,
  DiffViewer,
  Drawer,
  EnvelopeRenderer,
  JsonInspector,
} from '@operious/ui';
import { LineageRibbon } from '@operious/observability';
import type {
  MemoryProposalDto,
  RecommendationDto,
  SOPProposalDto,
} from '@operious/types';
import { useLocale } from '@/locale/provider';

type DrawerTarget =
  | { readonly kind: 'memory'; readonly value: MemoryProposalDto }
  | { readonly kind: 'sop'; readonly value: SOPProposalDto }
  | { readonly kind: 'recommendation'; readonly value: RecommendationDto };

export default function CognitionHubPage() {
  const { t } = useLocale();
  const memory = useMemoryProposals();
  const sop = useSOPProposals();
  const recs = useRecommendations();
  const [target, setTarget] = useState<DrawerTarget | null>(null);

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <p className="text-mono text-fg-subtle">/ cognition hub</p>
        <h1 className="font-display text-3xl text-fg">{t.cognition.title}</h1>
        <p className="max-w-3xl text-sm text-fg-muted">{t.cognition.description}</p>
        <Badge tone="pending">{t.cognition.approvalRequired}</Badge>
      </header>

      <section className="space-y-3">
        <h2 className="font-display text-xl text-fg">{t.cognition.memoryHeading}</h2>
        <EnvelopeRenderer
          status={memory.isLoading ? 'pending' : memory.isError ? 'error' : 'ok'}
          value={memory.data}
          error={memory.error ? { code: 'sdk_error', message: memory.error.message } : undefined}
        >
          {(page) => (
            <div className="grid gap-4 md:grid-cols-2">
              {page.items.map((proposal) => (
                <ProposalCard
                  key={proposal.proposalId as unknown as string}
                  title={proposal.title}
                  summary={proposal.summary}
                  badges={[`memory · ${proposal.kind}`, proposal.status, `by ${proposal.proposedBy}`]}
                  diff={proposal.diff}
                  onInspect={() => setTarget({ kind: 'memory', value: proposal })}
                />
              ))}
            </div>
          )}
        </EnvelopeRenderer>
      </section>

      <section className="space-y-3">
        <h2 className="font-display text-xl text-fg">{t.cognition.sopHeading}</h2>
        <EnvelopeRenderer
          status={sop.isLoading ? 'pending' : sop.isError ? 'error' : 'ok'}
          value={sop.data}
          error={sop.error ? { code: 'sdk_error', message: sop.error.message } : undefined}
        >
          {(page) => (
            <div className="grid gap-4 md:grid-cols-2">
              {page.items.map((proposal) => (
                <ProposalCard
                  key={proposal.proposalId as unknown as string}
                  title={`${proposal.sopName} (${proposal.version})`}
                  summary={proposal.summary}
                  badges={['SOP evolution', proposal.status]}
                  diff={proposal.diff}
                  onInspect={() => setTarget({ kind: 'sop', value: proposal })}
                />
              ))}
            </div>
          )}
        </EnvelopeRenderer>
      </section>

      <section className="space-y-3">
        <h2 className="font-display text-xl text-fg">
          {t.cognition.recommendationsHeading}
        </h2>
        <EnvelopeRenderer
          status={recs.isLoading ? 'pending' : recs.isError ? 'error' : 'ok'}
          value={recs.data}
          error={recs.error ? { code: 'sdk_error', message: recs.error.message } : undefined}
        >
          {(page) => (
            <div className="grid gap-4 md:grid-cols-2">
              {page.items.map((rec) => (
                <Card key={rec.recommendationId as unknown as string} tone="default" className="space-y-2">
                  <Badge tone="info">{rec.kind.replace(/_/g, ' ')}</Badge>
                  <h3 className="font-display text-base text-fg">{rec.title}</h3>
                  <p className="text-sm text-fg-muted">{rec.summary}</p>
                  <LineageRibbon lineage={rec.lineage} />
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setTarget({ kind: 'recommendation', value: rec })}
                  >
                    {t.common.viewDetails}
                  </Button>
                </Card>
              ))}
            </div>
          )}
        </EnvelopeRenderer>
      </section>

      <Drawer
        open={Boolean(target)}
        onClose={() => setTarget(null)}
        title={drawerTitle(target)}
        subtitle={drawerSubtitle(target)}
      >
        {target ? <DrawerContent target={target} /> : null}
      </Drawer>
    </div>
  );
}

const drawerTitle = (target: DrawerTarget | null): string => {
  if (!target) return '';
  if (target.kind === 'memory') return target.value.title;
  if (target.kind === 'sop') return `${target.value.sopName} ${target.value.version}`;
  return target.value.title;
};

const drawerSubtitle = (target: DrawerTarget | null): string | undefined => {
  if (!target) return undefined;
  if (target.kind === 'memory' || target.kind === 'sop') return target.value.summary;
  return target.value.summary;
};

const DrawerContent = ({ target }: { readonly target: DrawerTarget }) => {
  const { principal } = useAuth();
  const requestApproval = useRequestApproval();
  if (target.kind === 'recommendation') {
    return (
      <div className="space-y-4">
        <Badge tone="info">{target.value.kind.replace(/_/g, ' ')}</Badge>
        <LineageRibbon lineage={target.value.lineage} />
        <Card tone="inset" className="space-y-2">
          <p className="text-mono text-fg-subtle">evidence</p>
          <JsonInspector value={target.value.evidence} />
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <Badge tone="pending">{target.value.status}</Badge>
      <LineageRibbon lineage={target.value.lineage} />
      <DiffViewer diff={target.value.diff} />
      <Card tone="inset" className="space-y-3">
        <p className="text-mono text-fg-subtle">human-authority approval request</p>
        <p className="text-2xs text-fg-muted">
          The frontend never auto-approves. Submitting this opens a backend
          governed approval workflow; the backend confirms admission.
        </p>
        <Button
          variant="primary"
          size="sm"
          disabled={!principal || requestApproval.isPending}
          onClick={() => {
            if (!principal) return;
            requestApproval.mutate({
              proposalId: target.value.proposalId,
              approverId: principal.principalId,
              justification: 'pilot review',
              clientCorrelationId: newClientCorrelationId(),
            });
          }}
        >
          {requestApproval.isPending ? 'submitting…' : 'request approval'}
        </Button>
        {requestApproval.data ? (
          <Card tone="default" className="space-y-1">
            <Badge tone={requestApproval.data.accepted ? 'allow' : 'deny'}>
              {requestApproval.data.accepted ? 'admitted' : 'declined'}
            </Badge>
            <p className="text-mono text-fg-subtle">
              cid: {requestApproval.data.correlationId as unknown as string}
            </p>
            {requestApproval.data.reason ? (
              <p className="text-2xs text-fg-muted">{requestApproval.data.reason}</p>
            ) : null}
          </Card>
        ) : null}
        {requestApproval.error ? (
          <Card tone="default">
            <Badge tone="deny">error envelope</Badge>
            <p className="mt-2 text-2xs text-fg-muted">{requestApproval.error.message}</p>
          </Card>
        ) : null}
      </Card>
    </div>
  );
};

interface ProposalCardProps {
  readonly title: string;
  readonly summary: string;
  readonly badges: readonly string[];
  readonly diff: SOPProposalDto['diff'] | MemoryProposalDto['diff'];
  readonly onInspect: () => void;
}

const ProposalCard = ({ title, summary, badges, diff, onInspect }: ProposalCardProps) => (
  <Card tone="default" className="space-y-3">
    <div className="flex flex-wrap gap-1.5">
      {badges.map((badge) => (
        <Badge key={badge} tone="info">
          {badge}
        </Badge>
      ))}
    </div>
    <h3 className="font-display text-base text-fg">{title}</h3>
    <p className="text-sm text-fg-muted">{summary}</p>
    <DiffViewer diff={diff.slice(0, 2)} />
    <Button variant="ghost" size="sm" onClick={onInspect}>
      inspect
    </Button>
  </Card>
);
