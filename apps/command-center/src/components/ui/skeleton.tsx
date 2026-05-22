import { cn } from '@/lib/cn';

interface SkeletonProps {
  readonly className?: string;
  readonly rounded?: 'sm' | 'md' | 'lg' | 'full';
}

/**
 * Warm-gradient shimmer skeleton.
 *
 * Used to fill pending data slots without a spinner (loading states must be
 * skeleton screens per the motion doctrine). The shimmer animation is
 * defined in `tailwind.config.ts::keyframes.shimmer`.
 */
export const Skeleton = ({ className, rounded = 'sm' }: SkeletonProps) => {
  const roundedClass =
    rounded === 'full'
      ? 'rounded-full'
      : rounded === 'lg'
        ? 'rounded-lg'
        : rounded === 'md'
          ? 'rounded-md'
          : 'rounded-sm';
  return (
    <div
      className={cn(
        'shimmer relative overflow-hidden bg-line-subtle/60',
        roundedClass,
        className,
      )}
      aria-hidden
    />
  );
};
