import type { ProposalDiffSegmentDto } from '@operious/types';
import { cn } from '../utils';

interface DiffViewerProps {
  readonly diff: readonly ProposalDiffSegmentDto[];
  readonly className?: string;
}

const segmentToneClass: Record<
  ProposalDiffSegmentDto['changeType'],
  string
> = {
  added: 'border-l-2 border-signal-allow/60 bg-signal-allow/5',
  removed: 'border-l-2 border-signal-deny/60 bg-signal-deny/5',
  modified: 'border-l-2 border-signal-escalate/60 bg-signal-escalate/5',
  unchanged: 'border-l-2 border-line',
};

/**
 * Renders a backend-supplied proposal diff verbatim. The frontend NEVER
 * recomputes the diff — every segment, every change-type, every path is
 * exactly what the backend recorded. This preserves audit fidelity.
 */
export const DiffViewer = ({ diff, className }: DiffViewerProps) => (
  <div className={cn('space-y-1.5', className)}>
    {diff.length === 0 ? (
      <p className="text-mono text-fg-subtle">No diff segments emitted.</p>
    ) : (
      diff.map((segment, index) => (
        <div
          key={`${segment.path}-${index}`}
          className={cn(
            'rounded-sm pl-3 pr-2 py-2 font-mono text-2xs',
            segmentToneClass[segment.changeType],
          )}
        >
          <div className="flex items-center justify-between text-fg-subtle">
            <span>{segment.path}</span>
            <span className="uppercase tracking-wider">
              {segment.changeType}
            </span>
          </div>
          {segment.before !== undefined ? (
            <div className="mt-1 text-signal-deny/90">
              − {segment.before}
            </div>
          ) : null}
          {segment.after !== undefined ? (
            <div className="text-signal-allow/90">+ {segment.after}</div>
          ) : null}
        </div>
      ))
    )}
  </div>
);
