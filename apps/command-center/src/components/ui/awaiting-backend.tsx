import { Construction } from 'lucide-react';
import { EmptyState } from '@/components/ui/empty-state';
import { StatusPill } from '@/components/ui/status-pill';

interface AwaitingBackendProps {
  readonly endpoint: string;
  readonly description?: string;
}

/**
 * Honest empty state for surfaces whose backend endpoint is not yet wired in
 * this environment. The Command Center NEVER fabricates operational data \u2014
 * if the endpoint does not exist, we say so. Operators are not fooled by a
 * pretty placeholder.
 */
export const AwaitingBackend = ({
  endpoint,
  description,
}: AwaitingBackendProps) => (
  <div className="space-y-3">
    <StatusPill tone="pending" dot>
      awaiting backend endpoint
    </StatusPill>
    <EmptyState
      icon={Construction}
      title="This surface awaits a backend endpoint."
      description={
        description ??
        `The UI is ready; the operational backend route ${endpoint} has not yet been wired in this environment. Once the endpoint is live, this page will hydrate automatically.`
      }
    />
  </div>
);
