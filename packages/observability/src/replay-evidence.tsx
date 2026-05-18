import type { TraceBundleDto } from '@operious/types';
import { Card, Code, Stat } from '@operious/ui';

interface ReplayEvidenceProps {
  readonly bundle: TraceBundleDto;
}

/**
 * Replay evidence card — displays the backend-supplied replay digest and
 * counts. The frontend never recomputes the digest; it only renders what
 * the backend asserted as the byte-identical replay identity for this bundle.
 */
export const ReplayEvidence = ({ bundle }: ReplayEvidenceProps) => (
  <Card tone="default" className="space-y-3">
    <header className="flex items-center justify-between">
      <p className="text-mono text-fg-subtle">replay evidence</p>
      <p className="text-mono text-fg-dim">{bundle.observedAt}</p>
    </header>
    <div className="grid grid-cols-2 gap-2">
      <Stat
        label="trace nodes"
        value={bundle.nodes.length}
        hint="deterministically ordered"
      />
      <Stat
        label="correlation"
        value={(bundle.correlationId as unknown as string).slice(0, 12)}
        hint="backend authoritative"
      />
    </div>
    <div>
      <p className="text-mono text-fg-subtle mb-1.5">replay digest</p>
      <Code tone="block">{bundle.replayDigest}</Code>
    </div>
  </Card>
);
