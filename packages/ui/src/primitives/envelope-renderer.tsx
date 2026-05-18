import type { ReactNode } from 'react';
import { Badge } from './badge';
import { Card } from './card';
import { Code } from './code';

interface EnvelopeRendererProps<T> {
  readonly status: 'pending' | 'ok' | 'error';
  readonly value?: T;
  readonly error?: { code: string; message: string };
  readonly children: (value: T) => ReactNode;
  readonly emptyLabel?: string;
}

/**
 * Renders a backend envelope deterministically.
 *
 * The frontend NEVER hides backend errors behind toast popups; an error
 * envelope is rendered inline as a forensic artifact so the operator can
 * see exactly what the backend reported.
 */
export const EnvelopeRenderer = <T,>({
  status,
  value,
  error,
  children,
  emptyLabel = 'Awaiting backend response.',
}: EnvelopeRendererProps<T>) => {
  if (status === 'pending') {
    return (
      <Card tone="inset" className="text-mono text-fg-subtle">
        <Badge tone="pending">pending</Badge>
        <p className="mt-2">{emptyLabel}</p>
      </Card>
    );
  }
  if (status === 'error' || !value) {
    return (
      <Card tone="inset" className="space-y-2">
        <Badge tone="deny">error envelope</Badge>
        <Code tone="block">
          {JSON.stringify(error ?? { code: 'unknown', message: 'unknown error' }, null, 2)}
        </Code>
      </Card>
    );
  }
  return <>{children(value)}</>;
};
