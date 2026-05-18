import type { HTMLAttributes } from 'react';
import { cn } from '../utils';

interface CodeProps extends HTMLAttributes<HTMLElement> {
  readonly tone?: 'inline' | 'block';
}

export const Code = ({ tone = 'inline', className, ...rest }: CodeProps) => (
  <code
    className={cn(
      'font-mono text-2xs',
      tone === 'inline'
        ? 'rounded-sm bg-bg-inset border border-line-subtle px-1 py-0.5 text-fg-muted'
        : 'block rounded-md bg-bg-inset border border-line-subtle p-3 text-fg overflow-x-auto whitespace-pre',
      className,
    )}
    {...rest}
  />
);
