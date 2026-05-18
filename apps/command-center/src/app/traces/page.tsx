'use client';

import { useState } from 'react';
import { brand } from '@operious/shared';
import { useTraceBundle } from '@operious/sdk';
import { Button, Card, EnvelopeRenderer } from '@operious/ui';
import { LineageRibbon, ReplayEvidence, TraceTimeline } from '@operious/observability';
import type { CorrelationId } from '@operious/types';
import { useLocale } from '@/locale/provider';

export default function TraceInspectorPage() {
  const { t } = useLocale();
  const [draft, setDraft] = useState('corr-9f1a-0003');
  const [correlationId, setCorrelationId] = useState<CorrelationId | undefined>(
    brand<'CorrelationId'>('corr-9f1a-0003'),
  );
  const query = useTraceBundle(correlationId);

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <p className="text-mono text-fg-subtle">/ trace inspector</p>
        <h1 className="font-display text-3xl text-fg">{t.traces.title}</h1>
        <p className="max-w-3xl text-sm text-fg-muted">{t.traces.description}</p>
      </header>

      <Card tone="default" className="space-y-4">
        <form
          className="flex flex-wrap items-center gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            setCorrelationId(
              draft.trim() ? brand<'CorrelationId'>(draft.trim()) : undefined,
            );
          }}
        >
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder={t.traces.inputPlaceholder}
            className="w-80 rounded-sm border border-line bg-bg-inset px-3 py-2 font-mono text-2xs text-fg placeholder:text-fg-dim focus:border-accent"
          />
          <Button type="submit" variant="primary" size="sm">
            {t.traces.inspectAction}
          </Button>
          {correlationId ? (
            <span className="font-mono text-2xs text-fg-subtle">
              cid: {correlationId as unknown as string}
            </span>
          ) : null}
        </form>
      </Card>

      <EnvelopeRenderer
        status={query.isLoading ? 'pending' : query.isError ? 'error' : 'ok'}
        value={query.data}
        error={query.error ? { code: 'sdk_error', message: query.error.message } : undefined}
        emptyLabel={t.traces.empty}
      >
        {(bundle) => (
          <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
            <TraceTimeline bundle={bundle} />
            <div className="space-y-4">
              <ReplayEvidence bundle={bundle} />
              <Card tone="inset" className="space-y-2">
                <p className="text-mono text-fg-subtle">root lineage</p>
                <LineageRibbon
                  lineage={{
                    correlationId: bundle.correlationId,
                    sequence: 0,
                    observedAt: bundle.observedAt,
                  }}
                />
              </Card>
            </div>
          </div>
        )}
      </EnvelopeRenderer>
    </div>
  );
}
