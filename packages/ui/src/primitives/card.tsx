import type { HTMLAttributes } from 'react';
import { cn } from '../utils';

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  readonly tone?: 'default' | 'inset';
}

export const Card = ({ tone = 'default', className, ...rest }: CardProps) => (
  <div
    className={cn(
      'rounded-md border border-line p-4',
      tone === 'inset' ? 'bg-bg-inset' : 'bg-bg-raised',
      className,
    )}
    {...rest}
  />
);
