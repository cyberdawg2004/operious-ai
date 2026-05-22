import { cn } from '@/lib/cn';

export type SubstrateKind =
  | 'boundary'
  | 'governance'
  | 'coordination'
  | 'session'
  | 'execution'
  | 'supervisor'
  | 'arbitration'
  | 'hardening';

const KIND_CLASS: Record<SubstrateKind, string> = {
  boundary: 'bg-substrate-boundary',
  governance: 'bg-substrate-governance',
  coordination: 'bg-substrate-coordination',
  session: 'bg-substrate-session',
  execution: 'bg-substrate-execution',
  supervisor: 'bg-substrate-supervisor',
  arbitration: 'bg-substrate-arbitration',
  hardening: 'bg-substrate-hardening',
};

interface SubstrateDotProps {
  readonly kind: SubstrateKind;
  readonly size?: 'xs' | 'sm' | 'md';
  readonly className?: string;
}

const SIZE_CLASS = {
  xs: 'h-1.5 w-1.5',
  sm: 'h-2 w-2',
  md: 'h-2.5 w-2.5',
} as const;

/**
 * Substrate-colored dot. Used in the trace inspector legend and node bullets.
 */
export const SubstrateDot = ({
  kind,
  size = 'sm',
  className,
}: SubstrateDotProps) => (
  <span
    aria-hidden
    className={cn(
      'inline-block shrink-0 rounded-full',
      KIND_CLASS[kind],
      SIZE_CLASS[size],
      className,
    )}
  />
);

export const SUBSTRATE_KINDS: readonly SubstrateKind[] = [
  'boundary',
  'governance',
  'coordination',
  'session',
  'execution',
  'supervisor',
  'arbitration',
  'hardening',
] as const;
