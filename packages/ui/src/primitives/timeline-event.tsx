'use client';

import { useState, type ReactNode } from 'react';
import { cn } from '../utils';
import { Badge, type BadgeTone } from './badge';

interface TimelineEventProps {
  readonly sequence: number;
  readonly observedAt: string;
  readonly kind: string;
  readonly summary: ReactNode;
  readonly tone?: BadgeTone;
  readonly correlationId?: string;
  readonly children?: ReactNode;
  readonly className?: string;
}

/**
 * Forensic timeline event row. Always renders deterministically; expansion
 * state is local-only (presentational), it does not mutate any artifact.
 */
export const TimelineEvent = ({
  sequence,
  observedAt,
  kind,
  summary,
  tone = 'info',
  correlationId,
  children,
  className,
}: TimelineEventProps) => {
  const [expanded, setExpanded] = useState(false);
  const expandable = Boolean(children);

  return (
    <article
      className={cn(
        'border-l border-line pl-4 relative',
        'before:absolute before:-left-1.5 before:top-3 before:h-2.5 before:w-2.5 before:rounded-full before:bg-bg-raised before:border before:border-line',
        className,
      )}
    >
      <button
        type="button"
        onClick={() => expandable && setExpanded((prev) => !prev)}
        disabled={!expandable}
        className={cn(
          'w-full text-left rounded-md px-3 py-2 transition-colors',
          'border border-transparent',
          expandable && 'hover:border-line-subtle hover:bg-bg-raised/40',
          'disabled:cursor-default',
        )}
      >
        <header className="flex items-center gap-3 text-mono text-fg-subtle">
          <span>seq#{sequence.toString().padStart(4, '0')}</span>
          <span>·</span>
          <span>{observedAt}</span>
          <Badge tone={tone}>{kind}</Badge>
          {correlationId ? (
            <span className="ml-auto text-fg-dim">
              {correlationId.slice(0, 8)}
            </span>
          ) : null}
        </header>
        <p className="mt-1 text-sm text-fg">{summary}</p>
      </button>
      {expandable && expanded ? (
        <div className="mt-2 ml-3 mr-1 space-y-3">{children}</div>
      ) : null}
    </article>
  );
};
