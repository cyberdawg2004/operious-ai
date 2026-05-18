import { forwardRef, type ButtonHTMLAttributes } from 'react';
import { cn } from '../utils';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  readonly variant?: 'primary' | 'ghost' | 'danger' | 'subtle';
  readonly size?: 'sm' | 'md';
}

const baseClasses =
  'inline-flex items-center justify-center gap-2 rounded-sm border font-mono text-2xs uppercase tracking-wider transition-colors disabled:opacity-40 disabled:cursor-not-allowed';

const variantClasses: Record<NonNullable<ButtonProps['variant']>, string> = {
  primary:
    'bg-accent/15 border-accent/40 text-accent hover:bg-accent/25 hover:border-accent/60',
  ghost: 'bg-transparent border-line text-fg-muted hover:bg-bg-raised hover:text-fg',
  danger:
    'bg-signal-deny/10 border-signal-deny/40 text-signal-deny hover:bg-signal-deny/20',
  subtle: 'bg-bg-raised border-line-subtle text-fg-muted hover:text-fg',
};

const sizeClasses: Record<NonNullable<ButtonProps['size']>, string> = {
  sm: 'h-7 px-2.5 text-2xs',
  md: 'h-9 px-3.5 text-2xs',
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = 'primary', size = 'md', className, ...rest }, ref) => (
    <button
      ref={ref}
      className={cn(baseClasses, variantClasses[variant], sizeClasses[size], className)}
      {...rest}
    />
  ),
);
Button.displayName = 'Button';
