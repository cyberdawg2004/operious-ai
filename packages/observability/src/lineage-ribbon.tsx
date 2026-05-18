import type { Lineage } from '@operious/types';
import { Badge } from '@operious/ui';

interface LineageRibbonProps {
  readonly lineage: Lineage;
}

/**
 * Compact lineage display strip. The Trace Inspector and Operations Queue
 * both render this so an operator can immediately see correlation continuity
 * without expanding a row.
 */
export const LineageRibbon = ({ lineage }: LineageRibbonProps) => (
  <div className="flex flex-wrap items-center gap-2 text-mono text-fg-subtle">
    <Badge tone="info">seq#{lineage.sequence}</Badge>
    <span>{lineage.observedAt}</span>
    <span className="text-fg-dim">·</span>
    <span title={lineage.correlationId as unknown as string}>
      cid:{(lineage.correlationId as unknown as string).slice(0, 8)}
    </span>
    {lineage.parentCorrelationId ? (
      <>
        <span className="text-fg-dim">·</span>
        <span title={lineage.parentCorrelationId as unknown as string}>
          parent:{(lineage.parentCorrelationId as unknown as string).slice(0, 8)}
        </span>
      </>
    ) : null}
    {lineage.tenantId ? (
      <>
        <span className="text-fg-dim">·</span>
        <span>tenant:{lineage.tenantId as unknown as string}</span>
      </>
    ) : null}
  </div>
);
