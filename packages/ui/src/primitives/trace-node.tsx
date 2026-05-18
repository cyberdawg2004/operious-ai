'use client';

import type { ReactNode } from 'react';
import { Badge, type BadgeTone } from './badge';
import { Card } from './card';
import { JsonInspector } from './json-inspector';
import { cn } from '../utils';

interface TraceNodeProps {
  readonly kind: string;
  readonly tone?: BadgeTone;
  readonly title: ReactNode;
  readonly subtitle?: ReactNode;
  readonly observedAt: string;
  readonly sequence: number;
  readonly payload: unknown;
  readonly className?: string;
}

/**
 * Generic trace node renderer. Used by the Trace Inspector to display every
 * cross-substrate artifact identically: a header band of metadata + a
 * canonicalized JSON inspector for the payload.
 */
export const TraceNode = ({
  kind,
  tone = 'info',
  title,
  subtitle,
  observedAt,
  sequence,
  payload,
  className,
}: TraceNodeProps) => (
  <Card tone="default" className={cn('space-y-3', className)}>
    <header className="flex items-center gap-3 text-mono text-fg-subtle">
      <Badge tone={tone}>{kind}</Badge>
      <span>seq#{sequence.toString().padStart(4, '0')}</span>
      <span>·</span>
      <span>{observedAt}</span>
    </header>
    <div className="space-y-1">
      <h3 className="font-display text-base text-fg">{title}</h3>
      {subtitle ? <p className="text-sm text-fg-muted">{subtitle}</p> : null}
    </div>
    <JsonInspector value={payload} />
  </Card>
);
